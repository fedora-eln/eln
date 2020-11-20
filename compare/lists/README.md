# Lists for compare.py
These lists will eventually be pulled from where they are generated.  
But for now, while those parts are getting written, we have them stored as flat files here.

## exclude.txt
These packages should never be built, synced, or even counted.

We are still deciding where to put this list.  It is currently a list in eln-periodic.py

## nosync.txt
These are the packages that should not be synced from Fedora to RHEL and/or CentOS Stream.

This list is in a yaml file here - https://gitlab.cee.redhat.com/osci/distrobaker_config/-/blob/rhel9/distrobaker.yaml

Packages listed in nosync.txt and prepop.txt can overlap.  It's ok and encouranged.

## prepop.txt
These are packages that are PrePopulated in the Content Resolver workloads.

This list will eventually show up on Content Resolver - https://tiny.distro.builders/view--view-eln.html

The contents of this list are from https://tiny.distro.builders/view--view-eln--x86_64.html and doing a search of 000-placeholder.
You then take the binary rpm's from there and convert them to source rpm names.

