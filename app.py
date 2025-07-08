from flask import Flask, render_template, request, session, jsonify
from flask_session import Session
import pickle
import os
import requests
import google.generativeai as genai

# from youtube_search import YoutubeSearch


# ============ Gemini Setup ============
genai.configure(api_key="")
model = genai.GenerativeModel("gemini-1.5-flash")

# ============ Flask Setup ============
app = Flask(__name__)
app.secret_key = "cineverse_secret_key"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# ============ TMDB API ============
TMDB_API_KEY = ""

import requests
import time


def get_poster_by_title(title):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for attempt in range(2):  # Retry max twice
        try:
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}"
            response = requests.get(search_url, headers=headers)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            matched = next(
                (
                    r
                    for r in results
                    if r.get("title", "").strip().lower() == title.strip().lower()
                ),
                None,
            ) or (results[0] if results else None)

            if matched:
                poster_path = matched.get("poster_path")
                if poster_path:
                    return f"https://image.tmdb.org/t/p/w500{poster_path}"

        except requests.exceptions.RequestException as e:
            print("Attempt", attempt + 1, "failed:", e)
            time.sleep(1)  # small delay before retry

    return "https://via.placeholder.com/500x750?text=No+Poster+Available"


# ============ Models ============
MODELS = {"hindi": "models/hybrid_hindi.pkl", "telugu": "models/content_telugu.pkl"}
english_movies = pickle.load(open("models/movie_list.pkl", "rb"))
english_similarity = pickle.load(open("models/similarity.pkl", "rb"))


from youtube_search import YoutubeSearch


from pytube import Search


def get_youtube_embed_url(title):
    try:
        query = f"{title} official trailer"
        search = Search(query)
        result = search.results[0]
        video_url = result.watch_url
        video_id = video_url.split("v=")[-1]
        return f"https://www.youtube.com/embed/{video_id}"
    except Exception as e:
        print("YouTube trailer fetch error:", e)
        return None


def load_model(language):
    path = MODELS.get(language.lower())
    with open(path, "rb") as f:
        return pickle.load(f)


# ============ Routes ============


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/recommend", methods=["POST"])
def recommend():
    title = request.form.get("title").lower()
    language = request.form.get("language")

    # English Model Logic
    if language == "english":
        if title not in english_movies["title"].str.lower().values:
            return render_template(
                "recommend.html", error="Movie not found in English dataset."
            )

        index = english_movies[english_movies["title"].str.lower() == title].index[0]
        distances = sorted(
            list(enumerate(english_similarity[index])), reverse=True, key=lambda x: x[1]
        )
        results = []
        posters = []

        for i in distances[1:6]:
            movie_name = english_movies.iloc[i[0]].title
            poster = get_poster_by_title(movie_name)
            results.append({"title": movie_name, "combined": ""})
            posters.append(poster)

        zipped = zip(results, posters)
        return render_template(
            "recommend.html", results=zipped, movie=title.title(), language="English"
        )

    # Hindi / Telugu Models
    try:
        df, sim = load_model(language)
    except:
        return render_template(
            "recommend.html", error="Model not found for selected language."
        )

    matches = df[df["title"].str.lower() == title]
    if matches.empty:
        return render_template("recommend.html", error="Movie not found in dataset.")

    idx = matches.index[0]
    scores = sorted(list(enumerate(sim[idx])), key=lambda x: x[1], reverse=True)[1:6]

    if "combined" in df.columns:
        results = df.iloc[[i[0] for i in scores]][["title", "combined"]]
    else:
        results = df.iloc[[i[0] for i in scores]][["title", "overview"]]

    posters = [get_poster_by_title(movie_title) for movie_title in results["title"]]
    zipped = zip(results.to_dict(orient="records"), posters)
    return render_template(
        "recommend.html", results=zipped, movie=title.title(), language=language.title()
    )


@app.route("/trailer_url")
def trailer_url():
    title = request.args.get("title")
    url = get_youtube_embed_url(title)
    return jsonify({"url": url})


# ============ AI Chatbot ============
@app.route("/chatbot", methods=["GET", "POST"])
def chatbot():
    if request.method == "GET":
        session.clear()
    if "chat" not in session:
        session["chat"] = []

    if request.method == "POST":
        user_input = request.form["user_input"]
        session["chat"].append({"sender": "user", "text": user_input})
        prompt = f"You are a helpful movie assistant. Answer this: {user_input}"
        response = model.generate_content(prompt)
        session["chat"].append({"sender": "bot", "text": response.text})

    return render_template(
        "quiz_chatbot.html",
        title="🎬 CineVerse AI Chatbot",
        messages=session["chat"],
        action_url="/chatbot",
    )


# ============ AI Quiz ============
@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if request.method == "GET":
        session.clear()
    if "quiz_chat" not in session:
        session["quiz_chat"] = []
        session["quiz_answers"] = []
        session["quiz_step"] = 0
        first_q = model.generate_content(
            "Ask the first question to understand a user's movie taste."
        )
        session["quiz_chat"].append({"sender": "bot", "text": first_q.text})
        return render_template(
            "quiz_chatbot.html",
            title="🎯 AI Quiz",
            messages=session["quiz_chat"],
            action_url="/quiz",
        )

    if request.method == "POST":
        user_input = request.form["user_input"]
        session["quiz_chat"].append({"sender": "user", "text": user_input})
        session["quiz_answers"].append(user_input)
        session["quiz_step"] += 1

        if session["quiz_step"] < 5:
            next_q_prompt = f"Ask the next quiz question ({session['quiz_step']+1}) to understand preferences. Previous answers: {session['quiz_answers']}"
            next_question = model.generate_content(next_q_prompt)
            session["quiz_chat"].append({"sender": "bot", "text": next_question.text})
            return render_template(
                "quiz_chatbot.html",
                title="🎯 AI Quiz",
                messages=session["quiz_chat"],
                action_url="/quiz",
            )

        final_prompt = f"Based on these answers: {session['quiz_answers']}, suggest genres and 5 movies with short reasons."
        result = model.generate_content(final_prompt).text

        # Clear state
        session.pop("quiz_chat")
        session.pop("quiz_answers")
        session.pop("quiz_step")

        return render_template(
            "quiz_chatbot.html",
            title="🎯 AI Quiz",
            messages=[],
            result=result,
            action_url="/quiz",
        )


if __name__ == "__main__":
    app.run(debug=True)
