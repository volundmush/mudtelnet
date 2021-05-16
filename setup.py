import os
import sys
from setuptools import setup, find_packages

os.chdir(os.path.dirname(os.path.realpath(__file__)))

OS_WINDOWS = os.name == "nt"


def get_requirements():
    """
    To update the requirements for MudTelnet, edit the requirements.txt file.
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


# setup the package
setup(
    name="mudtelnet",
    version="0.8.0",
    author="Volund",
    maintainer="Volund",
    url="https://github.com/volundmush/mudtelnet-python",
    description="Simple Telnet library optimized for the MUD subset of Telnet.",
    license="MIT",
    long_description="""
    A bare-bones, standalone, modular and easily-extended library for handling turning bytes from sockets into 
    telnet events, and vice-versa. It does no networking and has no application logic, but is perfect for 
    creating a MUD project around.
    """,
    packages=["mudtelnet"],
   # install_requires=get_requirements(),
    zip_safe=False,
    classifiers=[
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.5",
        "Intended Audience :: Developers",
        "Topic :: Games/Entertainment :: Multi-User Dungeons (MUD)",
        "Topic :: Games/Entertainment :: Puzzle Games",
        "Topic :: Games/Entertainment :: Role-Playing",
        "Topic :: Games/Entertainment :: Simulation",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
    python_requires=">=3.5",
    project_urls={
        "Source": "https://github.com/volundmush/mudtelnet-python",
        "Issue tracker": "https://github.com/volundmush/mudtelnet-python/issues",
        "Patreon": "https://www.patreon.com/volund",
    },
)
