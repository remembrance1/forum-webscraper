from app import create_app

app = create_app()

if __name__ == "__main__":
    # For local dev. For Raspberry Pi deployment, use gunicorn:
    # gunicorn -w 1 -b 0.0.0.0:8000 'app:create_app()'
    app.run(debug=True, host="0.0.0.0", port=8000)
