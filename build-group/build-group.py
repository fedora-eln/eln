#!/usr/bin/python

from datetime import datetime as dt
from datetime import timedelta as td
import argparse
import os
import koji
from koji_cli.lib import watch_tasks
import logging


KOJI = koji.ClientSession('https://koji.fedoraproject.org/kojihub')
KOJI.gssapi_login(keytab=os.getenv('KOJI_KEYTAB'))

logger = logging.getLogger(__name__)


def request_sidetag(basetag="eln-build"):
    """Create sidetag for the output of the rebuild process"""

    sidetag = KOJI.createSideTag(basetag)["name"]
    logger.debug(f"Created sidetag {sidetag}")
    return sidetag

def is_eln(package):
    """Return True if package is should be rebuilt for ELN"""

    builds_in_ELN = KOJI.listTagged("eln", package=package)
    return bool(builds_in_ELN)

def create_rebuild_list(builds):
    """Prepare the list of packages to rebuild.

    For each package from the input list, get the full build info and check if
    package is a ELN package. If so, append it to the list.

    Return list of packages to rebuild. Each package is a dictionary as provided
    by koji.getBuild() API call.

    """

    to_rebuild = []

    for build in builds:
        build_data = KOJI.getBuild(build)
        if is_eln(build_data["package_name"]):
            to_rebuild.append(build_data)
        else:
            logger.info(f'Skipping {build_data["nvr"]} as it is not in ELN')

    logging.debug(to_rebuild)

    return to_rebuild

def rebuild_by_group(groups, target, **kwargs):

    opts={"scratch": True, 'fail_fast': True}
    
    opts.update(kwargs)

    
    logging.info(f'Processing {len(rebuild_groups)} groups')

    for group in groups:
        tasks = []
        for build in group:
            task_id = KOJI.build(
                src=build['extra']['source']['original_url'],
                target=target,
                opts=opts,
            )
            tasks.append(task_id)
        rv = watch_tasks(session, [tasks], poll_interval=10)

    return tasks


def group_rebuild_list(builds):
    """Split build in groups which can be rebuilt in parallel.

    Split timeline by completion timestamps.

    All builds which start before the minimal completion time stamp can be
    triggered simulataneously. Out of remaining builds, all builds which started
    before the second completion time can be started at once. An so on.
    """

    logging.debug(len(builds))
    completion_times = sorted([dt.fromtimestamp(build["completion_ts"]) for build in builds])
    logging.debug(f'Completion Times: {completion_times}')

    rebuild_groups = []

    for time in completion_times:
        rebuild_group = []
        reminder = []
        for build in builds:
            if dt.fromtimestamp(build["start_ts"]) < time:
                rebuild_group.append(build)
            else:
                reminder.append(build)
        if rebuild_group:
            builds = reminder
            rebuild_groups.append(rebuild_group)

    return rebuild_groups

def show_groups(groups):
    eta = 0
    for group in groups:
        nvrs = [build["nvr"] for build in group]
        durations = [build["completion_ts"] - build["start_ts"] for build in group]
        eta += max(durations)
        print(", ".join(nvrs))
    print(td(seconds=eta))

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("-v", "--verbose",
                        help="Enable debug logging",
                        action='store_true',
    )

    parser.add_argument("-s", "--scratch",
                        help="Run a scratch build only",
                        action='store_true',
    )

    input_group = parser.add_mutually_exclusive_group()

    input_group.add_argument("-i", "--input-tag",
                        help="Input sidetag",
    )

    input_group.add_argument("-b", "--build",
                        help="Space-separated list of builds",
                        nargs='+',
    )

    parser.add_argument("-o", "--output-tag",
                        help="Output sidetag",
    )


    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    logger.debug(args)

 #   args.input_tag = 'f35-build-side-38412'
    args.output_tag = 'eln-build-side-38508'

    if args.output_tag:
        output_tag = args.output_tag
    else:
        output_tag = request_sidetag()

    if args.input_tag:
        logger.info(f'Processing {args.input_tag}')
        builds = KOJI.listTagged(args.input_tag, latest=True)
    else:
        builds = args.build

    to_rebuild = create_rebuild_list(builds)

    rebuild_groups = group_rebuild_list(to_rebuild)

    show_groups(rebuild_groups)
    exit(0)
    
    rebuild_by_group(rebuild_groups, target=output_tag, scratch=True)
