import os
from app.providers.huggingface_provider import generate_video

VIDEO_PATH = "/app/data/assets/videos"


def generate_video_from_prompt(prompt: str, job_id: str):

    video_data = generate_video(prompt)

    file_path = f"{VIDEO_PATH}/{job_id}.mp4"

    with open(file_path, "wb") as f:
        f.write(video_data)

    return file_path
