# Momentum Sniper — نسخة الهاتف: تفك ضغط الحزمة أثناء البناء
# (ترفع momentum-sniper.zip كما هو إلى GitHub، وهذا الملف يفكها تلقائياً)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# فك ضغط أي حزمة zip موجودة في المستودع (Python مضمون التواجد)
COPY *.zip ./
RUN python -c "import zipfile,glob; zipfile.ZipFile(glob.glob('*.zip')[0]).extractall('.')" && rm -f *.zip

# Render يمرر PORT كمتغير بيئة
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
