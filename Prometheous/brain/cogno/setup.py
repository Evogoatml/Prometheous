from setuptools import setup, find_packages

setup(
    name="cogno",
    version="0.1.0",
    description="Cognitive substrate for multi-agent orchestrators",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.24.0",
    ],
    extras_require={
        "dev": ["pytest", "pytest-cov"],
    }
)
