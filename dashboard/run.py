"""Local dev entrypoint. Production uses a WSGI server (see DEPLOY-PYTHONANYWHERE.md)."""

from dashboard.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
