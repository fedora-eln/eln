#!/usr/bin/python3

import click
import getpass
import json
import koji
import logging
import sys

from collections import defaultdict


logger = logging.getLogger('eln_analyzer')


def get_eln_builds(session):
    builds = session.listTagged('eln-rebuild', inherit=False)
    builds.extend(session.listTagged('eln', inherit=False))

    eln_builds = defaultdict(list)
    for build in builds:
        eln_builds[build['package_name']].append(build)

    return eln_builds


def is_latest(eln_builds, package_name, task_id):
    """
    Determine whether the failed task is the most recent one attempted for this package

    :param eln_builds: Dictionary of ELN builds ( package_name->[build1, ..., buildN] )
    :param package_name: The name of the package
    :param task_id: The task ID of the failed build
    :return: True if no newer build has succeeded and been tagged into eln-rebuild. False if at least one build has
             succeeded since this one.
    """

    logger.debug("Checking if {} is the latest".format(package_name))

    if package_name not in eln_builds:
        return True

    # Hack: since task_id is monotonically increasing, we can assume that a build with a higher task_id must be newer.
    # Therefore if such an ID exists in the list of candidates, we can return False here, since a newer build must have
    # succeeded to be tagged into eln[-rebuild].
    logger.debug("eln_builds for {}: {}".format(package_name, eln_builds[package_name]))
    for candidate in eln_builds[package_name]:
        logger.debug("Existing tagged build of {}: {}".format(package_name, candidate))
        return False

    return True


def get_failure_details(session, task_id):
    details = defaultdict(dict)

    descendents = session.getTaskDescendents(task_id)
    for subtask in descendents[str(task_id)]:
        if subtask['state'] == koji.TASK_STATES['FAILED']:
            details[subtask['id']][subtask['label']] = subtask

    logger.debug("Failed subtasks: {}".format(details))
    return details


@click.command()
@click.option('-d', '--debug/--nodebug', default=False)
@click.option('-u', '--fas-user',
              help='The FAS user that created the builds',
              show_default='current user',
              default=lambda: getpass.getuser())
@click.option('--koji-url',
              help='The root of the Koji XMLRPC API',
              show_default=True,
              default='https://koji.fedoraproject.org/kojihub')
@click.option('--output-format',
              type=click.Choice(['packages', 'yaml'], case_sensitive=False),
              help='The output format to print',
              show_default=True,
              default='packages')
@click.option('--release-filter',
              help='A substring that must appear in the release field',
              show_default=True,
              default='eln')
def cli(debug, fas_user, koji_url, output_format, release_filter):
    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debugging mode enabled")
    else:
        logging.basicConfig()

    session = koji.ClientSession(koji_url)

    # Get the User ID
    fas_info = session.getUser(fas_user)
    if fas_info is None:
        print('{} is not a valid FAS user'.format(fas_user), file=sys.stderr)
        exit(1)

    candidates = session.listBuilds(
        userID=fas_info['id'],
        state=koji.BUILD_STATES['FAILED'],
        taskID=-1)

    eln_builds = get_eln_builds(session)

    failed_builds = dict()
    for candidate in candidates:
        if release_filter not in candidate['release']:
            continue

        package_name = candidate['package_name']
        if package_name in failed_builds:
            # Compare build times; we only care about the most recently built one
            if candidate['task_id'] < failed_builds[package_name]['task_id']:
                continue

        # Check whether a more recent build exists that succeeded
        if not is_latest(eln_builds, package_name, candidate['task_id']):
            logger.debug("Skipping {}. A newer build is already tagged.".format(candidate['nvr']))
            continue

        logger.debug("{} is a failed build".format(candidate['nvr']))
        failed_builds[package_name] = {'task_id': candidate['task_id'],
                                       'subtasks': get_failure_details(session, candidate['task_id'])}

    # Output the failed builds
    if output_format == 'yaml':
        print('{}'.format(json.dumps(failed_builds, indent=2)))
    else:
        for package_name in sorted(failed_builds.keys()):
            print('{}'.format(package_name))

if __name__ == "__main__":
    cli()
