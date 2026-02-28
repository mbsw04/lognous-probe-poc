FROM python:3.11-slim

# create a working directory
WORKDIR /app

# copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy application code
COPY . .

# default command
CMD ["python", "main.py"]
