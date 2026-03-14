from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "رسالة فارغة"}), 400

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "google/gemma-3-4b-it:free",
                "messages": [
                    {"role": "system", "content": "أنت مساعد ذكي ومفيد. أجب دائماً باللغة العربية بشكل واضح ومختصر."},
                    {"role": "user", "content": user_message}
                ]
            }
        )
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": f"خطأ: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
