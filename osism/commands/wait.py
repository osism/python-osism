# SPDX-License-Identifier: Apache-2.0

import os
import time
from types import SimpleNamespace

from cliff.command import Command
from loguru import logger
from osism import utils

# How long a STARTED task may go without emitting output before ``wait``
# starts reporting what it was last doing. Healthy tasks emit more or less
# continuously, so this only fires on a task that is genuinely wedged.
DEFAULT_STALL_REPORT_SECONDS = 600


def stall_report_seconds():
    """Seconds of silence before a STARTED task is reported.

    Read when ``wait`` runs rather than at import time: a typo in the
    variable must not stop the command from loading at all, and by then
    the logger is configured so the fallback is visible.

    A non-positive value is rejected along with an unparseable one --
    zero would report on every poll cycle, which is exactly the flood the
    per-task rate limiting exists to prevent.
    """
    raw = os.environ.get("OSISM_WAIT_STALL_REPORT")
    if raw is None:
        return DEFAULT_STALL_REPORT_SECONDS

    try:
        seconds = int(raw)
    except ValueError:
        seconds = 0

    if seconds <= 0:
        logger.warning(
            f"Ignoring invalid OSISM_WAIT_STALL_REPORT={raw!r}, "
            f"using {DEFAULT_STALL_REPORT_SECONDS}s"
        )
        return DEFAULT_STALL_REPORT_SECONDS

    return seconds


def peek_task_output(redis_conn, task_id, now=None):
    """Summarise a task's output stream without consuming it.

    ``fetch_task_output`` is destructive -- it ``xdel``s every entry it
    reads -- so it cannot be used to report on a task that is still
    running. Reading with ``xrevrange`` leaves the stream intact.

    Returns line count, the last line emitted and how long ago that was.
    ``lines == 0`` means the task has produced no output at all, which is
    itself a useful distinction: it separates a task hung mid-play from
    one that hung before writing its first line.
    """
    if now is None:
        now = time.time()

    entries = redis_conn.xrevrange(task_id, "+", "-", count=1)
    if not entries:
        return SimpleNamespace(lines=0, last_line=None, stalled_for=None, last_id=None)

    entry_id, fields = entries[0]
    last_ms = int(entry_id.decode().split("-")[0])

    return SimpleNamespace(
        lines=redis_conn.xlen(task_id),
        last_line=fields.get(b"content", b"").decode().rstrip("\n"),
        stalled_for=now - last_ms / 1000.0,
        last_id=entry_id.decode(),
    )


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--delay",
            default=1,
            type=int,
            help="Delay in second(s) between two task checks",
        )
        parser.add_argument(
            "--refresh",
            default=0,
            type=int,
            help="While waiting for all tasks refresh the list n times",
        )
        parser.add_argument(
            "--live",
            default=False,
            help="Show live output from a started task until it is finished",
            action="store_true",
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        ),
        parser.add_argument(
            "--output",
            default=False,
            help="Show output from a finished task",
            action="store_true",
        )
        parser.add_argument(
            "task_id", nargs="*", type=str, help="ID of tasks to wait for"
        )
        return parser

    def get_all_task_ids(self, i):
        task_ids = []
        for _, tasks in i.scheduled().items():
            for task in tasks:
                task_ids.append(task["id"])

        for _, tasks in i.active().items():
            for task in tasks:
                task_ids.append(task["id"])

        return sorted(task_ids)

    def _reset_peek_state(self):
        """Initialise the per-run state the stall peek keeps."""
        self._peek_disabled = False
        self._first_seen = {}
        self._last_report = {}
        self._stall_after = stall_report_seconds()

    def _should_report(self, task_id, marker, now):
        """Rate-limit stall reports for one task.

        The loop sleeps once per pass over all tasks, so at the default
        one-second delay an unthrottled report would emit a line per
        second for as long as a task stays wedged -- thousands of copies
        of a line that, by definition, is not changing.

        A report is emitted when the task is newly stalled, when its last
        line has advanced since the previous report (a fresh stall rather
        than the same one), and otherwise only once per
        the configured interval so the diagnosis stays visible near the tail
        of a long log.
        """
        previous = self._last_report.get(task_id)
        if previous is not None:
            marker_before, reported_at = previous
            if marker == marker_before and now - reported_at < self._stall_after:
                return False

        self._last_report[task_id] = (marker, now)
        return True

    def _report_stall(self, task_id):
        """Report what a long-silent STARTED task was last doing."""
        if self._peek_disabled:
            return

        try:
            peek = peek_task_output(utils.redis, task_id)
        except Exception as exc:
            # The non-``--live`` path never needed Redis, so a peek
            # failure must stay cosmetic. Report once, then stop trying.
            logger.warning(
                f"Stall reporting disabled: cannot read the output stream "
                f"of task {task_id}: {exc}"
            )
            self._peek_disabled = True
            return

        now = time.time()
        first_seen = self._first_seen.setdefault(task_id, now)

        if not peek.lines:
            silent_for = now - first_seen
            if silent_for >= self._stall_after and self._should_report(
                task_id, None, now
            ):
                logger.warning(
                    f"Task {task_id} has produced no output at all for "
                    f"{int(silent_for)}s"
                )
        elif peek.stalled_for >= self._stall_after and self._should_report(
            task_id, peek.last_id, now
        ):
            logger.warning(
                f"Task {task_id} has emitted no output for "
                f"{int(peek.stalled_for)}s ({peek.lines} lines so far). "
                f"Last output: {peek.last_line}"
            )

    def take_action(self, parsed_args):
        from celery import Celery
        from celery.result import AsyncResult
        from osism.tasks import Config

        delay = parsed_args.delay
        format = parsed_args.format
        live = parsed_args.live
        output = parsed_args.output
        refresh = parsed_args.refresh
        task_ids = sorted(parsed_args.task_id)

        do_refresh = False
        self._reset_peek_state()

        app = Celery("wait")
        app.config_from_object(Config)
        i = app.control.inspect()

        if not task_ids:
            logger.info("No task IDs specified, wait for all currently running tasks")
            task_ids = self.get_all_task_ids(i)
            do_refresh = True

        tmp_task_ids = []
        rc = 0
        while task_ids or do_refresh:
            if task_ids:
                task_id = task_ids.pop()
                result = AsyncResult(f"{task_id}", app=app)

                if result.state == "PENDING":
                    q = i.query_task(f"{task_id}")
                    if not len([x for x in q.values() if len(x)]):
                        if format == "log":
                            logger.info(f"Task {task_id} is unavailable")
                        elif format == "script":
                            print(f"{task_id} = UNAVAILABLE")
                    else:
                        if format == "log":
                            logger.info(f"Task {task_id} is in state PENDING")
                        elif format == "script":
                            print(f"{task_id} = PENDING")

                        tmp_task_ids.insert(0, task_id)

                elif result.state == "SUCCESS":
                    if format == "log":
                        logger.info(f"Task {task_id} is in state SUCCESS")
                    elif format == "script":
                        print(f"{task_id} = SUCCESS")

                    if output:
                        print(result.get())

                elif result.state == "STARTED":
                    if format == "log":
                        logger.info(f"Task {task_id} is in state STARTED")
                        self._report_stall(task_id)
                    elif format == "script":
                        print(f"{task_id} = STARTED")

                    if live:
                        utils.redis.ping()
                        try:
                            task_rc = utils.fetch_task_output(task_id)
                            if task_rc:
                                rc = task_rc
                        except TimeoutError:
                            logger.error(
                                f"Timeout while waiting for further output of task {task_id}"
                            )
                            rc = 1
                    else:
                        tmp_task_ids.insert(0, task_id)

                if not task_ids and tmp_task_ids:
                    logger.info(f"Wait {delay} second(s) until the next check")
                    time.sleep(delay)

                    if do_refresh:
                        task_ids = sorted(
                            list(set(self.get_all_task_ids(i) + tmp_task_ids))
                        )
                        tmp_task_ids = []
                    else:
                        task_ids = tmp_task_ids
            else:
                if refresh > 0:
                    refresh = refresh - 1
                    logger.info(
                        f"Wait {delay} second(s) until refresh of running tasks"
                    )
                    time.sleep(delay)
                    task_ids = self.get_all_task_ids(i)
                    tmp_task_ids = []
                else:
                    do_refresh = False

        return rc
