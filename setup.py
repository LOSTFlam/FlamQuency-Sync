from setuptools import setup, find_packages
import os

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="flamquency-sync",
    version="0.1.0",
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "flamquency=flamquency.main:main",
        ],
    },
    description="Terminal-based file synchronization with rollback",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    url="https://github.com/LOSTFlam/FlamQuency-Sync",
    author="LOSTFlam",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
)
