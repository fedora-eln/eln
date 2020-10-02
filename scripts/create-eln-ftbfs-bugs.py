#!/usr/bin/python3

# Chunks of code were lovingly borrowed from:
# * https://pagure.io/releng/blob/master/f/scripts/mass_rebuild_file_bugs.py
# * https://github.com/fedora-eln/eln/blob/master/scripts/find_eln_failures.py

import bugzilla
import click
import getpass
import koji
import logging
import os
import sys
import urllib
import tempfile

from xmlrpc.client import Fault


LOGGER = logging.getLogger(os.path.basename(__file__))
DRY_RUN = None

config = {
    "eln_tracking_bug": "ELNFTBFS",
    "product": "Fedora",
    "version": "ELN",
    "rhel_product": "Red Hat Enterprise Linux 9",
    "rhel_version": "9",
    "external_eln_ftbfs_url": "https://docs.fedoraproject.org/en-US/eln/",
    "internal_eln_ftbfs_url": None,
    "mirror_bugs": True,
    "kojihub": "https://koji.fedoraproject.org/kojihub",
    "koji_build_releasefilter": "eln",
    "koji_build_epoch": "2020-01-01 00:00:00",
}


def get_filed_bugs(bz, tracking_bug):
    """Query bugzilla for all bugs blocking the given tracking bug

    arguments:
    bz -- bugzilla client
    tracking_bug -- bug used to track failures
    """
    LOGGER.debug("Querying for blockers of tracking bug {}".format(tracking_bug))

    # lookup the tracking bug first in case it is an alias
    tbug = bz.getbug(tracking_bug)

    query = bz.build_query(blocked=str(tbug.id))
    return bz.query(query)


def get_comps_subcomp(bz, config):
    """Query bugzilla for all product components and sub-components.
    Return a dictionary mapping each component to its first sub-component,
    or None if has none.

    arguments:
    bz -- bugzilla client
    tracking_bug -- bug used to track failures
    """
    LOGGER.debug(
        "Querying for product {} sub-components".format(config["rhel_product"])
    )

    # query BZ for all of the product components and sub-components
    pdata = bz.product_get(
        names=[config["rhel_product"]],
        include_fields=[
            "name",
            "versions.name",
            "components.name",
            "components.sub_components",
        ],
    )

    comps_dict = {}
    for comp in pdata[0]["components"]:
        comps_dict[comp["name"]] = (
            comp["sub_components"][0]["name"] if comp["sub_components"] else None
        )

    LOGGER.debug("Returning component:sub-component map:\n{}".format(comps_dict))
    return comps_dict


DEFAULT_SUMMARY = "[ELN] {component}: FTBFS in {product} {version}"

DEFAULT_COMMENT = """{component} failed to build from source in {product} {version}

https://koji.fedoraproject.org/koji/taskinfo?taskID={task_id}
{extrainfo}

For resources to help remediate ELN build issues see:

{external_eln_ftbfs_url}

Please fix {component} in the Rawhide branch at your earliest convenience and
set the bug's status to ASSIGNED when you start fixing it.
"""

DEFAULT_EXTRAINFO = """
Note that {component} also appears to be failing to build from source in Fedora Rawhide.
Be sure to address that issue first. See BZ#{bugid}.
"""

DEFAULT_PRIV_COMMENT = """
Packages that are important to RHEL {rhel_version} need to build successfully
and correctly for Fedora ELN.

For additional internal resources to help remediate ELN build issues see:

{internal_eln_ftbfs_url}
"""


def report_failure(
    bz,
    config,
    component,
    sub_component,
    task_id,
    logs,
    summary=DEFAULT_SUMMARY,
    comment=DEFAULT_COMMENT,
    extrainfo="",
    priv_comment="",
):
    """This function files a new bugzilla bug for component with given
    arguments

    Keyword arguments:
    bz -- Bugzilla client
    config -- generic info about mass rebuild such as tracking_bug,
    Bugzilla product, version, wikipage
    component -- component (package) to file bug against
    sub_component -- sub-component to file bug against
    task_id -- task_id of failed build
    logs -- list of URLs to the log file to attach to the bug report
    summary -- short bug summary (if not default)
    comment -- first public comment describing the bug in more detail (if not default)
    extrainfo -- optional additional information to include in first public comment
    priv_comment -- optional private comment to add to bug report
    """

    format_values = dict(**config)
    format_values["task_id"] = task_id
    format_values["component"] = component
    format_values["extrainfo"] = extrainfo

    summary = summary.format(**format_values)
    comment = comment.format(**format_values)
    priv_comment = priv_comment.format(**format_values)

    data = {
        "product": config["rhel_product"],
        "component": component,
        "version": "unspecified",
        "short_desc": summary,
        "comment": comment,
        "blocks": config["eln_tracking_bug"],
        "rep_platform": "Unspecified",
        "bug_severity": "unspecified",
        "op_sys": "Unspecified",
        "bug_file_loc": "",
        "priority": "unspecified",
    }
    if sub_component:
        data["sub_component"] = sub_component
    if config["mirror_bugs"]:
        data["flags"] = [
            {"name": "mirror", "status": "+"},
        ]

    if priv_comment:
        priv_update = bz.build_update(comment=priv_comment, comment_private=True)
    else:
        priv_update = None

    LOGGER.debug("Bug creation data: {}".format(data))
    LOGGER.debug("Private comment data: {}".format(priv_update))

    if DRY_RUN:
        print("DRY_RUN: NOT creating the bug report")
        return

    try:
        print("Creating the bug report")
        bug = bz.createbug(**data)
        bug.refresh()
        print(bug)
        if priv_update:
            bz.update_bugs([bug.id], priv_update)
        attach_logs(bz, bug, logs)
    except Exception as ex:
        print(ex)
        # sys.exit(1)
        return None

    return bug


def attach_logs(bz, bug, logs):

    if isinstance(bug, int):
        bug = bz.getbug(bug)

    for log in logs:
        name = log.rsplit("/", 1)[-1]
        try:
            response = urllib.request.urlopen(log)
        except urllib.error.HTTPError as e:
            # sometimes there wont be any logs attached to the task.
            # skip attaching logs for those tasks
            if e.code == 404:
                print("Failed to attach {} log".format(name))
                continue
            else:
                break
        fp = tempfile.TemporaryFile()

        CHUNK = 2 ** 20
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            fp.write(chunk)

        filesize = fp.tell()
        # Bugzilla file limit, still possibly too much
        # FILELIMIT = 32 * 1024
        # Just use 32 KiB:
        FILELIMIT = 2 ** 15
        if filesize > FILELIMIT:
            fp.seek(filesize - FILELIMIT)
            comment = "file {} too big, only attached last {} bytes".format(
                name, FILELIMIT
            )
        else:
            comment = ""
            fp.seek(0)
        try:
            print("Attaching file %s to the ticket" % name)
            # arguments are: idlist, attachfile, description, ...
            attid = bz.attachfile(
                bug.id,
                fp,
                name,
                content_type="text/plain",
                file_name=name,
                comment=comment,
            )
            LOGGER.debug("Created attachment {} for bug {}".format(attid, bug.id))
        except Fault as ex:
            print(ex)
            raise

        finally:
            fp.close()


def get_failed_subtask(kojisession, task_id):
    """For a given build task_id, return the
    task_id of the first child that failed to build.
    """
    for child in kojisession.getTaskChildren(task_id):
        if child["state"] == koji.TASK_STATES["FAILED"]:  # 5 == Failed
            return child["id"]
    return 0


def get_koji_failed_build_taskid(ks, pkgname, release_filter, epoch):
    LOGGER.debug("get_koji_failed_build_taskid(pkgname={}) called".format(pkgname))

    pkgid = ks.getPackageID(pkgname)

    LOGGER.debug("Koji packageID for {} is {}".format(pkgname, pkgid))

    failed_builds = ks.listBuilds(
        packageID=pkgid,
        state=koji.BUILD_STATES["FAILED"],
        taskID=-1,
        createdAfter=epoch,
    )

    LOGGER.debug(
        "Koji query returned {} failed builds created after {}:\n{}".format(
            len(failed_builds), epoch, failed_builds
        )
    )

    # assume taskIDs are monotonically increasing...
    latest_failed_taskid = 0
    for build in failed_builds:
        if release_filter not in build["release"]:
            continue
        if build["task_id"] < latest_failed_taskid:
            continue
        latest_failed_taskid = build["task_id"]

    LOGGER.debug("Latest failed build taskid is {}".format(latest_failed_taskid))

    if not latest_failed_taskid:
        LOGGER.warning("Could not locate a failed build for package {}".format(pkgname))
        return 0

    subtask = get_failed_subtask(ks, latest_failed_taskid)

    LOGGER.debug("First detected subtask failure is {}".format(subtask))

    return subtask


def get_koji_task_logs(ks, taskid):
    work_url = "https://kojipkgs.fedoraproject.org/work"
    base_path = koji.pathinfo.taskrelpath(taskid)
    log_url = "%s/%s/" % (work_url, base_path)
    build_log = log_url + "build.log"
    root_log = log_url + "root.log"
    state_log = log_url + "state.log"
    return [build_log, root_log, state_log]


def listify(list_or_simple):
    if isinstance(list_or_simple, list):
        return list_or_simple
    else:
        return [list_or_simple]


@click.command()
@click.option(
    "--debug/--no-debug",
    is_flag=True,
    help="Enable debug output",
    show_default=True,
    default=False,
)
@click.option(
    "--dry-run/--no-dry-run",
    is_flag=True,
    help="Show what would be done without actually creating any Bugzilla bugs",
    show_default=True,
    default=False,
)
@click.option(
    "--input",
    "input_file",
    required=True,
    help="Input text file containing list of FTBFS packages, one per line",
)
@click.option(
    "--bugzilla",
    "bugzilla_url",
    help="The URL to the Bugzilla instance to use",
    show_default=True,
    default="https://bugzilla.redhat.com",
)
@click.option(
    "--sslverify/--no-sslverify",
    is_flag=True,
    help="Perform SSL validation checks connecting to Bugzilla?",
    show_default=True,
    default=True,
)
@click.option(
    "--api-key", type=str, help="Bugzilla API key", show_default=True, default=None,
)
@click.option(
    "--internal-eln-ftbfs-url",
    type=str,
    help="URL to an internal web page with resources for resolving ELN FTBFS errors",
    show_default=True,
    default=None,
)
@click.option(
    "--rawhide-tracking-bug",
    help="The current Rawhide FTBFS tracking bug",
    show_default=True,
    default="F34FTBFS",
)
def cli(
    debug,
    dry_run,
    input_file,
    bugzilla_url,
    sslverify,
    api_key,
    internal_eln_ftbfs_url,
    rawhide_tracking_bug,
):

    global DRY_RUN
    DRY_RUN = dry_run

    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        LOGGER.setLevel(logging.DEBUG)
        LOGGER.debug("Debugging mode enabled")
    else:
        logging.basicConfig()

    config["internal_eln_ftbfs_url"] = internal_eln_ftbfs_url

    if DRY_RUN:
        LOGGER.warning("Running in DRY RUN mode!")

    if not api_key:
        api_key = getpass.getpass("Enter Bugzilla API key: ")

    # establish Bugzilla client session
    LOGGER.debug("Creating Bugzilla session using instance {}".format(bugzilla_url))
    bz = bugzilla.Bugzilla(
        url="{}/xmlrpc.cgi".format(bugzilla_url), sslverify=sslverify, api_key=api_key
    )
    if not bz.logged_in:
        print("Bugzilla login failed. Bye bye.")
        sys.exit(1)

    LOGGER.debug("Creating Koji session using instance {}".format(config["kojihub"]))
    ks = koji.ClientSession(config["kojihub"])
    if not ks:
        print("Koji login failed. Bye bye.")
        sys.exit(1)

    # read list of ftbfs package names from file
    with open(input_file) as f:
        ftbfs_pkg_list = f.read().splitlines()
    # sort and remove any duplicates
    ftbfs_pkg_list = sorted(set(ftbfs_pkg_list))

    print(
        "Need to make sure bugs are filed for {} packages".format(len(ftbfs_pkg_list))
    )
    LOGGER.debug("Need to make sure bugs are filed for: {}".format(ftbfs_pkg_list))

    # get previously filed BZs
    filed_bugs = get_filed_bugs(bz, config["eln_tracking_bug"])
    eln_filed_bugs_components = {
        comp: bug.id for bug in filed_bugs for comp in listify(bug.component)
    }

    print(
        "Bugs have been previosly filed for {} packages".format(
            len(eln_filed_bugs_components)
        )
    )
    LOGGER.debug(
        "Bugs have been previosly filed for: {}".format(eln_filed_bugs_components)
    )

    # get filed Rawhide BZs
    filed_bugs = get_filed_bugs(bz, rawhide_tracking_bug)
    rawhide_open_bugs_components = {
        comp: bug.id
        for bug in filed_bugs
        if bug.status != "CLOSED"
        for comp in listify(bug.component)
    }

    print(
        "Rawhide bugs are still open for {} packages".format(
            len(rawhide_open_bugs_components)
        )
    )
    LOGGER.debug(
        "Rawhide bugs are still open for: {}".format(rawhide_open_bugs_components)
    )

    # get map of all components
    comps_subcomp = get_comps_subcomp(bz, config)

    for pkg in ftbfs_pkg_list:
        print("Checking package {}".format(pkg))

        if pkg not in comps_subcomp:
            print("Package {} does not exist in Bugzilla for the product!".format(pkg))
            continue

        if pkg in eln_filed_bugs_components:
            print(
                "BZ#{} for package {} has already been created".format(
                    eln_filed_bugs_components[pkg], pkg
                )
            )
            continue

        print("Need to create BZ for package {}".format(pkg))

        if pkg in rawhide_open_bugs_components:
            rawhide_bugid = rawhide_open_bugs_components[pkg]
            print(
                "Rawhide FTBFS BZ#{} is still open for package {}".format(
                    rawhide_bugid, pkg
                )
            )
            extrainfo = DEFAULT_EXTRAINFO.format(component=pkg, bugid=rawhide_bugid)
        else:
            extrainfo = ""

        task_id = get_koji_failed_build_taskid(
            ks, pkg, config["koji_build_releasefilter"], config["koji_build_epoch"]
        )

        if task_id:
            logs = get_koji_task_logs(ks, task_id)
        else:
            task_id = "Unavailable"
            logs = []

        LOGGER.debug("Logs for task_id {}: {}".format(task_id, logs))

        if internal_eln_ftbfs_url:
            priv_comment = DEFAULT_PRIV_COMMENT
        else:
            priv_comment = ""

        report_failure(
            bz,
            config,
            pkg,
            comps_subcomp[pkg],
            task_id,
            logs,
            extrainfo=extrainfo,
            priv_comment=priv_comment,
        )


if __name__ == "__main__":
    cli()
