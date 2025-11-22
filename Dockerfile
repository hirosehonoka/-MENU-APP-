FROM python:3.11
RUN apt-get update && apt-get install -y coinor-cbc
WORKDIR /app
COPY . /app
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD ["gunicorn", "menuapp:app"]