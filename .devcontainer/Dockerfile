FROM python:3.7

WORKDIR /workspaces

# Install Python dependencies from requirements.txt if it exists
COPY requirements_tests.txt .
RUN pip3 install -r requirements_tests.txt tox \
    && rm -f requirements_tests.txt

# Set the default shell to bash instead of sh
ENV SHELL /bin/bash
