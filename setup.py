from setuptools import setup, find_packages
import os
import re

# Версия читается из единственного источника правды — __init__.py.
# Копировать её сюда вручную значит гарантированно разъехаться на релизе.
def read_version():
    init_path = os.path.join("src", "flamquency", "__init__.py")
    with open(init_path) as f:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']',
                          f.read(), re.MULTILINE)
    if not match:
        raise RuntimeError(f"Не найдена __version__ в {init_path}")
    return match.group(1)

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="flamquency-sync",
    version=read_version(),
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "flamquency=flamquency.cli:main",
            "flamquency-tui=flamquency.main:main",
        ],
    },
    description="Terminal-based file synchronization with version control",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    url="https://github.com/LOSTFlam/FlamQuency-Sync",
    author="LOSTFlam",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
)
