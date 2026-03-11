import requests
import os

HF_API_KEY = os.getenv("HF_API_KEY")

IMAGE_MODEL = "stabilityai/stable-diffusion-2"
VIDEO_MODEL = "damo-vilab/modelscope-text-to-video-synthesis"

headers = {
    "Authorization": f"Bearer {HF_API_KEY}"
}


def generate_image(prompt: str):
    url = f"https://api-inference.huggingface.co/models/{IMAGE_MODEL}"

    response = requests.post(
        url,
        headers=headers,
        json={"inputs": prompt}
    )

    if response.status_code != 200:
        raise Exception(response.text)

    return response.content


def generate_video(prompt: str):

    url = f"https://api-inference.huggingface.co/models/{VIDEO_MODEL}"

    response = requests.post(
        url,
        headers=headers,
        json={"inputs": prompt}
    )

    if response.status_code != 200:
        raise Exception(response.text)

    return response.content
