#!/usr/bin/python3

import datetime
import json
import os
import requests
from jinja2 import Template

SCRIPTPATH = os.path.dirname(os.path.realpath(__file__))
TEMPLATEFILE = os.path.join(SCRIPTPATH, "compose-status.html.j2")

# Get our status data
json_url = 'https://odcs.fedoraproject.org/api/1/composes/?source=eln%23eln&compose_type=production'
jsonData = {}
jsonData = json.loads(requests.get(json_url, allow_redirects=True).text)

# Go through our status data
latest_compose = {}
compose_list = []
for this_compose in jsonData['items']:
    compose = {}
    compose['id'] = this_compose['id']
    compose['status'] = this_compose['state_name']
    compose['started'] = this_compose['time_submitted']
    compose['finished'] = this_compose['time_done']
    compose['url'] = this_compose['toplevel_url']
    compose['status_reason'] = this_compose['state_reason']
    if compose['status'] == "generating":
        compose['color'] = "#c9daf8"
    elif compose['status'] == "done":
        compose['color'] = "#d9ead3"
    else:
        compose['color'] = "#f4cccc"
    compose_list.append(compose)
    if not latest_compose and not compose['status'] == "generating":
        latest_compose = compose

with open(TEMPLATEFILE) as fi:
    tmpli = Template(fi.read())
with open('output/compose-status.html', 'w') as w:
    w.write(tmpli.render(
        this_date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        last=latest_compose,
        composes=compose_list))
