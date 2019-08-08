FROM python:3.7

WORKDIR /workspace

# Install Python dependencies from requirements.txt if it exists
COPY requirements_tests.txt /workspace/
RUN pip3 install -r requirements_tests.txt

# Set the default shell to bash instead of sh
ENV SHELL /bin/bash
