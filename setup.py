from setuptools import setup

VERSION = "0.52.1"

setup(
    name="hass-nabucasa",
    version=VERSION,
    license="GPL v3",
    author="Nabu Casa, Inc.",
    author_email="opensource@nabucasa.com",
    url="https://www.nabucasa.com/",
    download_url="https://github.com/NabuCasa/hass-nabucasa/tarball/{}".format(VERSION),
    description=("Home Assistant cloud integration by Nabu Casa, Inc."),
    long_description=(""),
    classifiers=[
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    keywords=["homeassistant", "cloud"],
    zip_safe=False,
    platforms="any",
    packages=["hass_nabucasa"],
    python_requires=">=3.8",
    install_requires=[
        "pycognito==2022.01.0",
        "snitun==0.31.0",
        "acme==1.22.0",
        "cryptography>=2.8,<37.0",
        "attrs>=19.3",
        "pytz>=2019.3",
        "aiohttp>=3.6.1",
        "atomicwrites==1.4.0",
    ],
)
