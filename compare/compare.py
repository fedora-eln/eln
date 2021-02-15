#!/usr/bin/python3

import koji

import argparse
import datetime
import jinja2
import json
import logging
import os
import re
import requests
import rpm
import sys

SCRIPTPATH = os.path.dirname(os.path.realpath(__file__))

class BuildSource:
    def __init__(
        self,
        source_id=None,
        infra=None,
        tag=None,
        make_cache=True,
        product=None,
        distro_url=None,
        distro_view=None,
    ):
        """Setup a source of the builds

        :infra: Koji or Brew session,
        :tag: Koji or Brew tag
        """

        if source_id:
            infra, tag, product, distro_url, distro_view = self._configure_source(source_id)

        self.infra = infra
        self.tag = tag
        self.product = product
        self.distro_url = distro_url
        self.distro_view = distro_view
        self.cache = {}

        if make_cache:
            self.make_cache()

    def __str__(self):
        return f'{self.tag}'

    def _configure_source(self, source_id):
        distro_url = "https://tiny.distro.builders"
        distro_view = "eln"
        if source_id == "rawhide":
            infra = koji.ClientSession('https://koji.fedoraproject.org/kojihub')
            tag = infra.getFullInheritance('rawhide')[0]['name']
            product = "Rawhide"
        if source_id == "fedora":
            infra = koji.ClientSession('https://koji.fedoraproject.org/kojihub')
            tag = "f34-cr-eln"
            product = "Fedora34"
        if source_id == "eln":
            infra = koji.ClientSession('https://koji.fedoraproject.org/kojihub')
            tag = "eln"
            product = "ELN"
        if source_id == "stream":
            infra = koji.ClientSession('https://kojihub.stream.rdu2.redhat.com/kojihub')
            # FIXME?
            tag = "c9s-candidate"
            product = "Stream9"
            distro_url = "https://raw.githubusercontent.com/minimization/lists/main"
            distro_view = "c9s"
        if source_id == "rhel":
            # FIXME
            infra = koji.ClientSession('https://brewhub.engineering.redhat.com/brewhub')
            tag = "rhel-9.0.0-alpha-candidate"
            product = "RHEL9"
            distro_url = "https://raw.githubusercontent.com/minimization/lists/main"
            distro_view = "c9s"

        return infra, tag, product, distro_url, distro_view

    def get_build(self, package):
        """Find the latest build of a package available in the build source

        Return None if there is no builds found
        """

        if self.cache:
            if package in self.cache:
                logging.debug(f'Read cached for {package} in {self}')
                return self.cache[package]
            else:
                logging.debug(f'Package {package} not found in cached {self}')
                return None

        builds = self.infra.listTagged(self.tag, package=package, latest=True)

        if builds:
            return builds[0]
        else:
            return None

    def make_cache(self):
        """Fetch all builds from tag"""

        logging.debug(f'Make cache for {self}...')
        builds = self.infra.listTagged(self.tag, latest=True)
        for build in builds:
            self.cache[build["name"]] = build
        logging.debug(f'Done making cache for {self}')


class Comparison:

    status = {
        -5: "PPLACE",
        -4: "NOSYNC",
        -3: "EXTRA",
        -2: "ERROR",
        -1: "NEW",
        0: "SAME",
        1: "OLD",
        2: "NONE",
    }

    def __init__(self, content, source1, source2):
        self.content = content
        self.source1 = source1
        self.source2 = source2

        distro_url = source2.distro_url
        distro_view = source2.distro_view
        arches = ["aarch64", "ppc64le", "s390x", "x86_64"]

        # Setup PackagePlaceholder package list
        self.pplace_packagelist = []

        for arch in arches:
            placeholderJsonData = {}
            placeholderURL = (
                "{distro_url}"
                "/view-placeholder-srpm-details--view-{distro_view}--{arch}.json"
            ).format(distro_url=distro_url, distro_view=distro_view, arch=arch)
            placeholderJsonData = json.loads(requests.get(placeholderURL, allow_redirects=True).text)
            for placeholder_source in placeholderJsonData:
                logging.debug(f'Placeholder {placeholder_source} put on list')
                if not placeholder_source in self.pplace_packagelist:
                    self.pplace_packagelist.append(placeholder_source)

        # The nosync list should be coming from the distrobaker config yaml file 
        # https://gitlab.cee.redhat.com/osci/distrobaker_config/-/raw/rhel9/distrobaker.yaml
        # For now just use a flat file
        nosync_f = os.path.join(SCRIPTPATH, "lists", "nosync.txt")
        self.nosync_packagelist = open(nosync_f).read().splitlines()

        self.results = {}

    def compare_one(self, package):
        """Return comparison data for a package

        Return dictionary with items: status, nvr1, nvr2.
        """
        if package not in content:
            logging.warning(f'Package {package} is not in the content set')

        if package in self.results:
            return self.results[package]

        build1 = self.source1.get_build(package)
        build2 = self.source2.get_build(package)

        if package in self.pplace_packagelist:
            logging.debug(f'Package {package} pre-populated')
            return {
                "status": self.status[-5],
                "nvr1": None if not build1 else build1['nvr'],
                "nvr2": None if not build2 else build2['nvr'],
            }

        if package in self.nosync_packagelist:
            logging.debug(f'Package {package} is a not synced')
            return {
                "status": self.status[-4],
                "nvr1": None if not build1 else build1['nvr'],
                "nvr2": None if not build2 else build2['nvr'],
            }

        if not build1:
            logging.warning(f'Package {package} not found in {source1}')
            return {
                "status": self.status[-2],
                "nvr1": None,
                "nvr2": None if not build2 else build2['nvr'],
            }

        if not build2:
            logging.debug(f'Package {package} not found in {source2}')
            return {
                "status": self.status[2],
                "nvr1": build1["nvr"],
                "nvr2": None,
            }

        return {
                "status": self.status[compare_builds(build1, build2)],
                "nvr1": build1["nvr"],
                "nvr2": build2["nvr"],
        }

    def add_extras(self):
        """Add packages from source2 which don't belong to the content set to the comparison with the status EXTRA

        Return dictionary of comparison items for such packages.
        """

        extras = {}

        for package, build in self.source2.cache.items():
            if package not in self.content and package not in self.pplace_packagelist:
                logging.debug(f'Extras package {package} found in {self.source2}')
                extras[package] = {
                    "status": self.status[-3],
                    "nvr1": None,
                    "nvr2": build["nvr"],
                }

        self.results.update(extras)

        return extras

    def compare_content(self):
        for package in self.pplace_packagelist:
            logging.debug(f'Processing package {package}')
            self.results[package] = self.compare_one(package)
        for package in content:
            logging.debug(f'Processing package {package}')
            self.results[package] = self.compare_one(package)
        return self.results

    def count(self):
        stats = {}
        for item in self.results.values():
            value = item["status"]
            if value not in stats:
                stats[value] = 0
            stats[value] += 1
        stats["total"] = sum(stats.values())
        return stats

    def mcount(self):
        mstats = {}
        mstats_list = ["SAME","NEW","OLD","NONE","ERROR"]
        for item in self.results.values():
            value = item["status"]
            if value in mstats_list:
                if value not in mstats:
                    mstats[value] = 0
                mstats[value] += 1
        mstats["total"] = sum(mstats.values())
        return mstats

    def results_by_status(self):
        """Return dictionary of lists of packages from comparison

        Dictionary key is the status of the comparison. Dictionary value is a
        list of tuples describing the package and nvr's.
        """
        data = {}
        for package, info in self.results.items():
            if info["status"] not in data:
                data[info["status"]] = []
            data[info["status"]].append((package, info["nvr1"], info["nvr2"]))

        return data

    def render(self, tmpl_path="templates", output_path="output", fmt="all"):
        os.makedirs(output_path, exist_ok=True)

        j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
        templates = j2_env.list_templates(extensions="j2")
        if fmt != "all":
            fmtlist = fmt.split(",")
            templates = [
                name for name in templates if name.split(".")[-2] in fmtlist
            ]

        for tmpl_name in templates:
            tmpl = j2_env.get_template(tmpl_name)
            tmpl.stream(
                source1=self.source1,
                source2=self.source2,
                product1=self.source1.product,
                product2=self.source2.product,
                results=self.results,
                stats=self.count(),
                mstats=self.mcount(),
                date=datetime.datetime.now()
            ).dump(
                os.path.join(
                    output_path,
                    tmpl_name[:-3],
                )
            )


def get_content(distro_url="https://tiny.distro.builders", distro_view="eln"):
    """Builds the full list of packages for the distro from the Content Resolver

    Merges result for all architectures.
    """
    merged_packages = set()

    arches = ["aarch64", "ppc64le", "s390x", "x86_64"]
    which_source = ["source", "buildroot-source"]

    # excludes should be changed to a URL / git repo somewhere
    # Currently they are variables in eln-periodic.py
    # For now just use a flat file
    exclude_f = os.path.join(SCRIPTPATH, "lists", "exclude.txt")
    exclude_packagelist = open(exclude_f).read().splitlines()

    for arch in arches:
        for this_source in which_source:
            url = (
                "{distro_url}"
                "/view-{this_source}-package-name-list--view-{distro_view}--{arch}.txt"
            ).format(distro_url=distro_url, this_source=this_source, distro_view=distro_view, arch=arch)

            logging.debug("downloading {url}".format(url=url))

            r = requests.get(url, allow_redirects=True)
            for line in r.text.splitlines():
                if not line:
                    continue
                if line in exclude_packagelist:
                    continue
                merged_packages.add(line)

    logging.debug("Found a total of {} packages".format(len(merged_packages)))

    return merged_packages


def evr(build):
    """Get epoch, version, release data from the build

    We currently reset Epoch value to 0, because we have number of cases where
    epoch of a package in Rawhide is different from that of ELN.

    We remove dist tag data from the release, so that we can compare nvr's
    between different distributions.
    """

    epoch = "0"

    version = build['version']
    p = re.compile(".(fc|eln|el)[0-9]*")
    release = re.sub(p, "", build['release'])

    return (epoch, version, release)


def compare_builds(build1, build2):
    """Compare versions of two builds

    Return -1, 0 or 1 if version of build1 is lesser, equal or greater than build2.
    """

    evr1 = evr(build1)
    evr2 = evr(build2)

    return rpm.labelCompare(evr1, evr2)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-v", "--verbose",
        help="Enable debug logging",
        action='store_true',
    )

    parser.add_argument(
        "-c", "--cache",
        action="store_true",
        help="Enable cache of build sources",
    )

    parser.add_argument(
        "-t", "--templates",
        default=os.path.join(sys.path[0], "templates"),
        help="Path to templates for the rendered content",
    )

    parser.add_argument(
        "-f", "--format",
        default="all",
        help="Comma-separated list of output formats. Supported: json, html, txt, all.",
    )

    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Path where to store rendered results",
    )

    parser.add_argument(
        "source1",
        choices=["rawhide", "fedora", "eln", "stream", "rhel"],
        help="First source of package builds",
    )

    parser.add_argument(
        "source2",
        choices=["rawhide", "fedora", "eln", "stream", "rhel"],
        help="Second source of package builds",
    )

    parser.add_argument(
        "packages",
        nargs='*',
        default=None,
        help="Optional list of packages to compare. Disables caching.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    source1 = BuildSource(source_id=args.source1, make_cache=args.cache)
    source2 = BuildSource(source_id=args.source2, make_cache=args.cache)

    if args.packages:
        content = args.packages
        args.cache = False
    else:
        content = sorted(
            get_content(distro_url=source2.distro_url, distro_view=source2.distro_view)
        )

    C = Comparison(content, source1, source2)

    C.compare_content()
    C.add_extras()

    logging.info(C.count())
    C.render(output_path=args.output, tmpl_path=args.templates, fmt=args.format)

    with open("content.txt", "w") as f:
        for pkg_name in content:
            f.write(pkg_name + "\n")

    results = C.results_by_status()

    with open("untag.txt", "w") as f:
        for pkg_info in results.get("EXTRA", []):
            f.write(pkg_info[2] + "\n")

    with open("rebuild.txt", "w") as f:
        for pkg_info in results.get("NONE", []) + results.get("OLD", []):
            f.write(pkg_info[1] + "\n")

    with open("ftbfs.txt", "w") as f:
        for pkg_info in results.get("NONE", []):
            f.write(pkg_info[0] + "\n")
