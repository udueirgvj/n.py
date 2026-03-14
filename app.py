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
        return jsonify({"reply": "رسالة فارغة"}), 400

    if not OPENROUTER_API_KEY:
        return jsonify({"reply": "❌ API Key غير موجود في البيئة"})

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://n-py.onrender.com",
                "X-Title": "AI Chatbot"
            },
            json={
                "model": "openai/gpt-3.5-turbo",
                "messages": [
                    {"role": "user", "content": user_message}
                ]
            },
            timeout=30
        )
        result = response.json()
        if "choices" in result:
            reply = result["choices"][0]["message"]["content"]
            return jsonify({"reply": reply})
        else:
            return jsonify({"reply": f"❌ خطأ من API: {str(result)}"})
    except Exception as e:
        return jsonify({"reply": f"❌ خطأ: {str(e)}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
