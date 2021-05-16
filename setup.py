import os
import sys
from setuptools import setup, find_packages

os.chdir(os.path.dirname(os.path.realpath(__file__)))

VERSION_PATH = os.path.join("mudtelnet", "VERSION.txt")
OS_WINDOWS = os.name == "nt"


def get_requirements():
    """
    To update the requirements for Shinma, edit the requirements.txt file.
    """
    with open("requirements.txt", "r") as f:
        req_lines = f.readlines()
    reqs = []
    for line in req_lines:
        # Avoid adding comments.
        line = line.split("#")[0].strip()
        if line:
            reqs.append(line)
    return reqs


def get_version():
    """
    When updating the Evennia package for release, remember to increment the
    version number in evennia/VERSION.txt
    """
    return open(VERSION_PATH).read().strip()


def package_data():
    """
    By default, the distribution tools ignore all non-python files.

    Make sure we get everything.
    """
    file_set = []
    for root, dirs, files in os.walk("mudtelnet"):
        for f in files:
            if ".git" in f.split(os.path.normpath(os.path.join(root, f))):
                # Prevent the repo from being added.
                continue
            file_name = os.path.relpath(os.path.join(root, f), "mudtelnet")
            file_set.append(file_name)
    return file_set


# setup the package
setup(
    name="mudtelnet",
    version=get_version(),
    author="Volund",
    maintainer="Volund",
    url="https://github.com/volundmush/mudtelnet-python",
    description="",
    license="???",
    long_description="""
    
    """,
    long_description_content_type="text/markdown",
    packages=find_packages(),
   # install_requires=get_requirements(),
    package_data={"": package_data()},
    zip_safe=False,
    classifiers=[

    ],
    python_requires=">=3.7",
    project_urls={
        "Source": "https://github.com/volundmush/mudtelnet-python",
        "Issue tracker": "https://github.com/volundmush/mudtelnet-python/issues",
        "Patreon": "https://www.patreon.com/volund",
    },
)
