#!/usr/bin/env bash
set -x

ANSIBLE_COLLECTIONS_PATH=/usr/local/lib/python3.11/site-packages/ansible_collections

COLLECTIONS=(
amazon
arista
awx
azure
check_point
chocolatey
cisco
cloudscale_ch
cyberark
dellemc
f5networks
fortinet
gluster
google
hetzner
hpe
ibm
infinidat
infoblox
inspur
junipernetworks
lowlydba
mellanox
netapp
netapp_eseries
ngine_io
ovirt
purestorage
sensu
servicenow
splunk
t_systems_mms
theforeman
vmware
vultr
vyos
wti
)

COLLECTIONS_COMMUNITY=(
aws
azure
ciscosmb
digitalocean
fortios
google
hrobot
mongodb
okd
routeros
sap
sap_libs
skydive
sops
vmware
windows
zabbix
)

for collection in ${COLLECTIONS[@]}; do
    rm -rf $ANSIBLE_COLLECTIONS_PATH/$collection
done

for collection in ${COLLECTIONS_COMMUNITY[@]}; do
    rm -rf $ANSIBLE_COLLECTIONS_PATH/community/$collection
done
