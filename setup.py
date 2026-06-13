#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import setuptools

with open("README.md", "r", encoding="utf-8") as fp:
    long_description = fp.read()

setuptools.setup(
    name="nsq2mariadb",
    version="0.1.4",
    author="Lars Wallenborn",
    description="generic NSQ → MariaDB transporter with per-topic Python mapper classes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/larsborn/nsq2mariadb",
    project_urls={
        "Bug Tracker": "https://github.com/larsborn/nsq2mariadb/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "pynsq",
        "pymysql",
    ],
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.9",
)
