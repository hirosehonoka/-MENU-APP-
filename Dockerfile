FROM python:3.11
RUN apt-get update && apt-get install -y coinor-cbc
WORKDIR /app
COPY ./source/main/menuapp.py /app/menuapp.py
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD ["gunicorn", "menuapp:app"]