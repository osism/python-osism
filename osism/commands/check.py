# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import os
import random
import stat

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism import settings

try:
    import docker

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


# Default path for configuration directory
DEFAULT_CONFIGURATION_PATH = "/opt/configuration"

# Docker socket path
DOCKER_SOCKET_PATH = "/var/run/docker.sock"


def get_file_info(filepath: str) -> dict[str, object]:
    """Get file metadata including inode, mtime, size, and content hash for small files."""
    try:
        st = os.stat(filepath)
        file_hash: str | None = None

        # For small files (< 1MB), also compute a hash for content comparison
        if st.st_size < 1024 * 1024 and stat.S_ISREG(st.st_mode):
            try:
                with open(filepath, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()
            except (IOError, OSError):
                pass

        return {
            "inode": st.st_ino,
            "mtime": st.st_mtime,
            "size": st.st_size,
            "mode": st.st_mode,
            "uid": st.st_uid,
            "gid": st.st_gid,
            "is_link": os.path.islink(filepath),
            "hash": file_hash,
        }
    except (OSError, IOError) as e:
        return {"error": str(e)}


def collect_file_info(
    base_path: str, max_files: int = 100000
) -> dict[str, dict[str, object]]:
    """Collect file information for all files under base_path."""
    file_info: dict[str, dict[str, object]] = {}
    count = 0

    for root, dirs, files in os.walk(base_path, followlinks=False):
        # Skip .git, venv, __pycache__ directories
        for skip in [".git", "venv", "__pycache__"]:
            if skip in dirs:
                dirs.remove(skip)

        for name in files + dirs:
            if count >= max_files:
                logger.warning(f"Reached max file limit ({max_files}), stopping scan")
                return file_info

            filepath = os.path.join(root, name)
            # Skip symlinks
            if os.path.islink(filepath):
                continue
            relpath = os.path.relpath(filepath, base_path)
            file_info[relpath] = get_file_info(filepath)
            count += 1

    return file_info


def parse_stat_output(output: str) -> dict[str, dict[str, object]]:
    """Parse stat output from container into a dict of file info."""
    file_info: dict[str, dict[str, object]] = {}
    current_file = None

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("FILE:"):
            current_file = line[5:].strip()
            file_info[current_file] = {}
        elif current_file and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "inode":
                file_info[current_file]["inode"] = int(value)
            elif key == "size":
                file_info[current_file]["size"] = int(value)
            elif key == "mtime":
                file_info[current_file]["mtime"] = float(value)
            elif key == "hash":
                file_info[current_file]["hash"] = value if value != "NONE" else None
            elif key == "error":
                file_info[current_file]["error"] = value

    return file_info


class Mount(Command):
    """Check bind mount integrity for /opt/configuration.

    This command verifies that the bind mount is consistent by comparing
    the container's view of /opt/configuration with a fresh mount.

    When files are replaced on the host (e.g., through git operations that
    delete and recreate files), the container might see stale data if it
    holds file handles to old inodes. This command detects such mismatches.
    """

    def get_parser(self, prog_name):
        parser = super(Mount, self).get_parser(prog_name)
        parser.add_argument(
            "--path",
            default=DEFAULT_CONFIGURATION_PATH,
            help=f"Path to check (default: {DEFAULT_CONFIGURATION_PATH})",
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log", "table"],
        )
        parser.add_argument(
            "--max-files",
            default=100000,
            type=int,
            help="Maximum number of files to scan (default: 100000)",
        )
        parser.add_argument(
            "--registry",
            default="registry.osism.cloud/dockerhub",
            help="Container registry to use (default: registry.osism.cloud/dockerhub)",
        )
        parser.add_argument(
            "--image",
            default="alpine:latest",
            help="Docker image to use for fresh mount check (default: alpine:latest)",
        )
        parser.add_argument(
            "--volume-name",
            default=None,
            help="Docker volume name to use instead of auto-detection",
        )
        parser.add_argument(
            "--host-path",
            default=None,
            help="Host path for the bind mount (for manual specification)",
        )
        parser.add_argument(
            "--check-content",
            action="store_true",
            default=False,
            help="Also verify file content hashes (slower but more thorough)",
        )
        return parser

    def _get_container_id(self) -> str | None:
        """Get the current container's ID."""
        # Try from cgroup (works on most Docker setups)
        try:
            with open("/proc/self/cgroup", "r") as f:
                for line in f:
                    if "docker" in line or "containerd" in line:
                        # Extract container ID from path
                        parts = line.strip().split("/")
                        for part in reversed(parts):
                            if len(part) == 64 or len(part) == 12:
                                return part[:12]
        except (IOError, OSError):
            pass

        # Try from hostname (container ID is often the hostname)
        try:
            hostname = os.uname().nodename
            if len(hostname) == 12:
                return hostname
        except Exception:
            pass

        # Try from /proc/self/mountinfo
        try:
            with open("/proc/self/mountinfo", "r") as f:
                for line in f:
                    if "/docker/containers/" in line:
                        # Extract container ID
                        idx = line.find("/docker/containers/")
                        if idx != -1:
                            rest = line[
                                idx + len("/docker/containers/") :  # noqa: E203
                            ]
                            container_id = rest.split("/")[0]
                            if len(container_id) >= 12:
                                return container_id[:12]
        except (IOError, OSError):
            pass

        return None

    def _get_mount_source(self, mount_path: str) -> str | None:
        """Get the source path for a bind mount."""
        # Try /proc/self/mountinfo
        try:
            with open("/proc/self/mountinfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 5:
                        mount_point = parts[4]
                        if mount_point == mount_path:
                            # Find the source - it's after the " - " separator
                            try:
                                separator_idx = parts.index("-")
                                if separator_idx + 2 < len(parts):
                                    source = parts[separator_idx + 2]
                                    if source.startswith("/"):
                                        return source
                            except ValueError:
                                pass
        except (IOError, OSError):
            pass

        return None

    def _get_volume_mount_info(
        self, client, container_id: str, mount_path: str
    ) -> dict | None:
        """Get volume/bind mount information from Docker API."""
        try:
            container = client.containers.get(container_id)
            for mount in container.attrs.get("Mounts", []):
                if mount.get("Destination") == mount_path:
                    return {
                        "type": mount.get("Type"),
                        "source": mount.get("Source"),
                        "name": mount.get("Name"),
                        "driver": mount.get("Driver"),
                    }
        except Exception as e:
            logger.debug(f"Could not get mount info from Docker API: {e}")

        return None

    def _run_fresh_container(
        self,
        client,
        image: str,
        mount_source: str,
        mount_path: str,
        check_content: bool,
        max_files: int,
    ) -> str:
        """Run a fresh container to collect file info from the mount."""
        # Script to collect file info - create operator user (UID/GID 45000) first
        # Write inner script to file to avoid quote escaping issues
        operator_user = settings.OPERATOR_USER
        script = f"""#!/bin/sh
addgroup -g 45000 {operator_user} 2>/dev/null
adduser -D -u 45000 -G {operator_user} {operator_user} 2>/dev/null

cat > /tmp/scan.sh << 'SCANEOF'
cd "{mount_path}"
find . -maxdepth 10 \\( -name .git -o -name venv -o -name __pycache__ \\) -prune -o \\( -type f -o -type d \\) -print 2>/dev/null | head -{max_files} | while read file; do
    [ "$file" = "." ] && continue
    relpath="${{file#./}}"
    [ -z "$relpath" ] && continue
    echo "FILE:$relpath"
    if [ -e "$file" ]; then
        inode=$(stat -c "%i" "$file" 2>&1)
        if [ $? -eq 0 ]; then
            echo "INODE:$inode"
            echo "SIZE:$(stat -c "%s" "$file")"
            echo "MTIME:$(stat -c "%Y" "$file")"
"""
        if check_content:
            script += """
            if [ -f "$file" ] && [ $(stat -c %s "$file" 2>/dev/null || echo 9999999) -lt 1048576 ]; then
                hash=$(md5sum "$file" 2>/dev/null | cut -d' ' -f1)
                echo "HASH:${hash:-NONE}"
            else
                echo "HASH:NONE"
            fi
"""
        else:
            script += '            echo "HASH:NONE"\n'

        script += """
        else
            echo "ERROR:$inode"
        fi
    else
        echo "ERROR:File not found"
    fi
done
SCANEOF

chmod +x /tmp/scan.sh
su {operator_user} -c "/bin/sh /tmp/scan.sh"
"""

        try:
            # Run container with the same mount
            container = client.containers.run(
                image,
                command=["/bin/sh", "-c", script],
                volumes={mount_source: {"bind": mount_path, "mode": "ro"}},
                remove=True,
                network_mode="none",
                user="root",
                stdout=True,
                stderr=True,
            )
            return container.decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"Failed to run fresh container: {e}")

    def _compare_file_info(
        self, local_info: dict, fresh_info: dict, check_content: bool
    ) -> tuple[list, list, list, list]:
        """Compare local and fresh file info, return mismatches."""
        inode_mismatches = []
        content_mismatches = []
        missing_in_local = []
        missing_in_fresh = []

        all_files = set(local_info.keys()) | set(fresh_info.keys())

        for filepath in sorted(all_files):
            local = local_info.get(filepath)
            fresh = fresh_info.get(filepath)

            if local is None:
                missing_in_local.append(filepath)
                continue

            if fresh is None:
                missing_in_fresh.append(filepath)
                continue

            if "error" in local or "error" in fresh:
                continue

            # Check inode mismatch (the key indicator of stale mounts)
            local_inode = local.get("inode")
            fresh_inode = fresh.get("inode")
            if local_inode and fresh_inode and local_inode != fresh_inode:
                inode_mismatches.append(
                    {
                        "file": filepath,
                        "local_inode": local_inode,
                        "fresh_inode": fresh_inode,
                    }
                )

            # Check content hash mismatch (if enabled and both have hashes)
            if check_content:
                local_hash = local.get("hash")
                fresh_hash = fresh.get("hash")
                if local_hash and fresh_hash and local_hash != fresh_hash:
                    content_mismatches.append(
                        {
                            "file": filepath,
                            "local_hash": local_hash,
                            "fresh_hash": fresh_hash,
                        }
                    )

        return inode_mismatches, content_mismatches, missing_in_local, missing_in_fresh

    def take_action(self, parsed_args):
        path = parsed_args.path
        format = parsed_args.format
        max_files = parsed_args.max_files
        registry = parsed_args.registry
        image = f"{registry}/{parsed_args.image}" if registry else parsed_args.image
        volume_name = parsed_args.volume_name
        host_path = parsed_args.host_path
        check_content = parsed_args.check_content

        # Check if path exists
        if not os.path.exists(path):
            if format == "log":
                logger.error(f"Path does not exist: {path}")
            elif format == "script":
                print(f"FAILED: Path does not exist: {path}")
            return 1

        # Check if Docker is available
        if not DOCKER_AVAILABLE:
            if format == "log":
                logger.error("Docker Python library not available")
            elif format == "script":
                print("FAILED: Docker Python library not available")
            return 1

        # Check if Docker socket exists
        if not os.path.exists(DOCKER_SOCKET_PATH):
            if format == "log":
                logger.error(f"Docker socket not found at {DOCKER_SOCKET_PATH}")
                logger.info("The Docker socket must be mounted in this container")
            elif format == "script":
                print(f"FAILED: Docker socket not found at {DOCKER_SOCKET_PATH}")
            return 1

        try:
            client = docker.from_env()
        except Exception as e:
            if format == "log":
                logger.error(f"Failed to connect to Docker: {e}")
            elif format == "script":
                print(f"FAILED: Failed to connect to Docker: {e}")
            return 1

        # Get container ID
        container_id = self._get_container_id()
        if format == "log":
            if container_id:
                logger.info(f"Current container ID: {container_id}")
            else:
                logger.warning("Could not determine current container ID")

        # Determine mount source
        mount_source = host_path

        if not mount_source and container_id:
            mount_info = self._get_volume_mount_info(client, container_id, path)
            if mount_info:
                if format == "log":
                    logger.info(f"Mount type: {mount_info.get('type')}")
                    logger.info(f"Mount source: {mount_info.get('source')}")

                if mount_info.get("type") == "bind":
                    mount_source = mount_info.get("source")
                elif mount_info.get("type") == "volume":
                    if volume_name:
                        mount_source = volume_name
                    else:
                        mount_source = mount_info.get("name") or mount_info.get(
                            "source"
                        )

        if not mount_source:
            # Try to get from mountinfo
            mount_source = self._get_mount_source(path)

        if not mount_source:
            if format == "log":
                logger.error(
                    f"Could not determine mount source for {path}. "
                    "Please specify --host-path or --volume-name"
                )
            elif format == "script":
                print(f"FAILED: Could not determine mount source for {path}")
            return 1

        if format == "log":
            logger.info(f"Using mount source: {mount_source}")
            logger.info(f"Collecting file info from local view of {path}...")

        # Collect local file info
        local_info = collect_file_info(path, max_files)
        if format == "log":
            logger.info(f"Found {len(local_info)} files/directories locally")

        # Pull image if needed
        if format == "log":
            logger.info(f"Ensuring image {image} is available...")

        try:
            client.images.pull(image)
        except Exception as e:
            if format == "log":
                logger.warning(f"Could not pull image {image}: {e}")
                logger.info("Trying to use existing image...")

        # Run fresh container
        if format == "log":
            logger.info("Running fresh container to collect file info...")

        try:
            fresh_output = self._run_fresh_container(
                client, image, mount_source, path, check_content, max_files
            )
        except Exception as e:
            if format == "log":
                logger.error(f"Failed to run fresh container: {e}")
            elif format == "script":
                print(f"FAILED: {e}")
            return 1

        # Parse fresh container output
        fresh_info = parse_stat_output(fresh_output)
        if format == "log":
            logger.info(f"Found {len(fresh_info)} files/directories in fresh mount")

        # Compare
        if format == "log":
            logger.info("Comparing file information...")

        inode_mismatches, content_mismatches, missing_local, missing_fresh = (
            self._compare_file_info(local_info, fresh_info, check_content)
        )

        # Report results
        has_issues = bool(inode_mismatches or content_mismatches or missing_local)

        if format == "log":
            if inode_mismatches:
                logger.error(
                    f"Found {len(inode_mismatches)} inode mismatch(es) - STALE MOUNT DETECTED!"
                )
                for m in inode_mismatches[:10]:
                    logger.error(
                        f"  {m['file']}: local inode={m['local_inode']}, "
                        f"fresh inode={m['fresh_inode']}"
                    )
                if len(inode_mismatches) > 10:
                    logger.error(f"  ... and {len(inode_mismatches) - 10} more")
            else:
                logger.info("No inode mismatches detected")

            if content_mismatches:
                logger.warning(
                    f"Found {len(content_mismatches)} content hash mismatch(es)"
                )
                for m in content_mismatches[:10]:
                    logger.warning(f"  {m['file']}: hashes differ")
                if len(content_mismatches) > 10:
                    logger.warning(f"  ... and {len(content_mismatches) - 10} more")

            if missing_local:
                logger.error(
                    f"Found {len(missing_local)} file(s) missing in local view "
                    "(exist on host but not visible in container)"
                )
                for f in missing_local[:10]:
                    logger.error(f"  {f}")
                if len(missing_local) > 10:
                    logger.error(f"  ... and {len(missing_local) - 10} more")

            if missing_fresh:
                logger.info(
                    f"Found {len(missing_fresh)} file(s) only in local view "
                    "(may be temporary files)"
                )

            if has_issues:
                logger.error("Mount integrity check FAILED")
                logger.info(
                    "Consider restarting containers that access this mount, "
                    "or remounting the volume"
                )
            else:
                logger.info("Mount integrity check PASSED")

        elif format == "table":
            if inode_mismatches:
                print("\nInode Mismatches (STALE MOUNT):")
                table = [
                    [m["file"], m["local_inode"], m["fresh_inode"]]
                    for m in inode_mismatches
                ]
                print(
                    tabulate(
                        table,
                        headers=["File", "Local Inode", "Fresh Inode"],
                        tablefmt="psql",
                    )
                )

            if content_mismatches:
                print("\nContent Hash Mismatches:")
                table = [
                    [m["file"], m["local_hash"][:8], m["fresh_hash"][:8]]
                    for m in content_mismatches
                ]
                print(
                    tabulate(
                        table,
                        headers=["File", "Local Hash", "Fresh Hash"],
                        tablefmt="psql",
                    )
                )

            if missing_local:
                print("\nFiles Missing in Container (exist on host):")
                for f in missing_local:
                    print(f"  {f}")

            print()
            if has_issues:
                print("RESULT: FAILED - Mount integrity issues detected")
            else:
                print("RESULT: PASSED - Mount is consistent")

        elif format == "script":
            if has_issues:
                print("FAILED")
                if inode_mismatches:
                    print(f"INODE_MISMATCHES:{len(inode_mismatches)}")
                if content_mismatches:
                    print(f"CONTENT_MISMATCHES:{len(content_mismatches)}")
                if missing_local:
                    print(f"MISSING_IN_CONTAINER:{len(missing_local)}")
            else:
                print("PASSED")

        return 1 if has_issues else 0


class Inode(Command):
    """Quick inode check for specific files in /opt/configuration.

    This is a lightweight alternative to 'check mount' that only checks
    specific files without spawning a fresh container.
    """

    def get_parser(self, prog_name):
        parser = super(Inode, self).get_parser(prog_name)
        parser.add_argument(
            "files",
            nargs="*",
            default=[],
            help="Specific files to check (relative to configuration path)",
        )
        parser.add_argument(
            "--path",
            default=DEFAULT_CONFIGURATION_PATH,
            help=f"Base path (default: {DEFAULT_CONFIGURATION_PATH})",
        )
        parser.add_argument(
            "--format",
            default="table",
            help="Output type",
            const="table",
            nargs="?",
            choices=["script", "log", "table"],
        )
        return parser

    def take_action(self, parsed_args):
        path = parsed_args.path
        files = parsed_args.files
        format = parsed_args.format

        # If no files specified, select random files from environments/* and inventory/*
        if not files:
            files = []
            # Collect files per subdirectory in environments and inventory
            for base_dir in ["environments", "inventory"]:
                base_path = os.path.join(path, base_dir)
                if not os.path.isdir(base_path):
                    continue

                # Get immediate subdirectories
                subdirs = []
                for entry in os.listdir(base_path):
                    entry_path = os.path.join(base_path, entry)
                    if os.path.isdir(entry_path):
                        subdirs.append(entry)

                # For each subdirectory, collect files/dirs and pick random samples
                for subdir in subdirs:
                    subdir_path = os.path.join(base_path, subdir)
                    # Skip symlinks
                    if os.path.islink(subdir_path):
                        continue
                    subdir_entries = []
                    # Add the subdirectory itself
                    subdir_entries.append(os.path.relpath(subdir_path, path))
                    for root, dirs, filenames in os.walk(
                        subdir_path, followlinks=False
                    ):
                        # Skip .git and venv directories
                        for skip in [".git", "venv", "__pycache__"]:
                            if skip in dirs:
                                dirs.remove(skip)
                        # Add directories (skip symlinks)
                        for name in dirs:
                            dirpath = os.path.join(root, name)
                            if not os.path.islink(dirpath):
                                relpath = os.path.relpath(dirpath, path)
                                subdir_entries.append(relpath)
                        # Add files (skip symlinks)
                        for name in filenames:
                            filepath = os.path.join(root, name)
                            if not os.path.islink(filepath):
                                relpath = os.path.relpath(filepath, path)
                                subdir_entries.append(relpath)
                    # Pick up to 2 random entries per subdirectory
                    if subdir_entries:
                        files.extend(
                            random.sample(subdir_entries, min(2, len(subdir_entries)))
                        )

                # Also check files directly in environments/ or inventory/
                direct_files = []
                for entry in os.listdir(base_path):
                    entry_path = os.path.join(base_path, entry)
                    # Skip symlinks
                    if os.path.islink(entry_path):
                        continue
                    if os.path.isfile(entry_path):
                        relpath = os.path.relpath(entry_path, path)
                        direct_files.append(relpath)
                if direct_files:
                    files.extend(random.sample(direct_files, min(2, len(direct_files))))

        results = []
        for relpath in files:
            filepath = os.path.join(path, relpath)
            # Skip symlinks
            if os.path.islink(filepath):
                continue
            if os.path.exists(filepath):
                info = get_file_info(filepath)
                entry_type = "Dir" if os.path.isdir(filepath) else "File"
                results.append(
                    {
                        "file": relpath,
                        "type": entry_type,
                        "inode": info.get("inode"),
                        "size": info.get("size"),
                    }
                )

        if format == "log":
            for r in results:
                logger.info(
                    f"{r['file']}: type={r['type']}, inode={r['inode']}, size={r['size']}"
                )

        elif format == "table":
            print("Inode snapshot of random files from environments/ and inventory/.")
            print(
                "This shows the container's current view - use 'check mount' to compare with host.\n"
            )
            table = [
                [
                    r["file"],
                    r["type"],
                    r["inode"] or "-",
                    r["size"] or "-",
                ]
                for r in results
            ]
            print(
                tabulate(
                    table, headers=["Path", "Type", "Inode", "Size"], tablefmt="psql"
                )
            )

        elif format == "script":
            for r in results:
                print(f"{r['type']}:{r['file']}:{r['inode']}")

        return 0
