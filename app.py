from flask import Flask, request, jsonify
import openai
from openai import OpenAI
from flask_cors import CORS
import os
import time
import requests
import json
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["fertilityforlife.com", "http://127.0.0.1:5000", "http://127.0.0.1:8080"]}})

app.config['ENV'] = os.getenv('FLASK_ENV')

# Function to retrieve secrets from AWS Secrets Manager
def get_secret(secret_name):
    client = boto3.client('secretsmanager', region_name='eu-west-2') 
    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        return secret
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Error retrieving secrets: {e}")
        return None

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# OPENAI_API_KEY = get_secret('OPENAI_API_KEY')

# Access the API key from the environment variable
client = OpenAI(api_key=OPENAI_API_KEY)

assistant_id = os.getenv('ASSISTANT_ID')
# assistant_id = get_secret('ASSISTANT_ID')

summarization_assistant_id = os.getenv('SUMMARIZATION_ASSISTANT_ID')
# summarization_assistant_id = get_secret('SUMMARIZATION_ASSISTANT_ID')

def summarise_conversation(conversation): 
    # Create a new thread
    thread = client.beta.threads.create()
    thread_id = thread.id
    # add the conversation to the thread
    for message in conversation:
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role=message['role'],
            content=message['content']
        )

    # Run the summarization assistant
    run_response = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=summarization_assistant_id
    )

    # Poll the run status until it is completed
    run_id = run_response.id
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "assistants=v2"
    }
    while True:
        response = requests.get(f"https://api.openai.com/v1/threads/{thread_id}/runs/{run_id}", headers=headers)
        run_status = response.json()
        if run_status['status'] == 'failed':
            return "Summarization failed"
        if run_status['status'] == 'completed':
            break
        time.sleep(1)  # Wait for 1 second before polling again
    
    # Fetch the summary
    response = requests.get(f"https://api.openai.com/v1/threads/{thread_id}/messages", headers=headers)
    messages = response.json()['data']
    
    # Extract the assistant's summary
    summary = None
    for message in messages:
        if message['role'] == 'assistant':
            summary = message['content'][0]['text']['value']
            break

    return summary


@app.route('/', methods=['GET'])
def home():
    return "Welcome to the Fertility Center Assistant!"



@app.route('/api/chat', methods=['POST'])
def chat():
    user_input = request.json['message']
    # Check if there is a thread in the request. If not, create a new thread.
    if 'thread_id' in request.json:
        thread_id = request.json['thread_id']
    else:
        thread = client.beta.threads.create()
        thread_id = thread.id
    
    print(thread_id)

    # Create message in the thread
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_input
    )

    # Run the assistant
    run_response = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id
    )

    # Poll the run status until it is completed
    run_id = run_response.id
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "assistants=v2"
    }

    while True:
        response = requests.get(f"https://api.openai.com/v1/threads/{thread_id}/runs/{run_id}", headers=headers)
        run_status = response.json()['status']
        if run_status == "failed":
            print(run_status)
            break
        print(run_status)
        time.sleep(1)  # Wait for 1 second before polling again
        if run_status == "completed":
            print(run_status)
            break

    # Fetch the results
    # Make an additional API call to fetch the assistant's response
    response = requests.get(f"https://api.openai.com/v1/threads/{thread_id}/messages", headers=headers)
    messages = response.json()['data']
    
    # Extract the assistant's response
    assistant_response = None
    for message in messages:
        if message['role'] == 'assistant':
            assistant_response = message['content'][0]['text']['value']
            break

    if assistant_response is None:
        return jsonify({"error": "No assistant response found"}), 500

    # print(assistant_response)
    
    return jsonify({"response": assistant_response, "thread_id": thread_id})

@app.route('/api/endChat', methods=['POST'])
def end_chat():
    if 'thread_id' in request.json:
        thread_id = request.json['thread_id']
        # Retireve the messages from the thread
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "assistants=v2"
        }
        response = requests.get(f"https://api.openai.com/v1/threads/{thread_id}/messages", headers=headers)
        messages = response.json()['data']  
        # Reverse the messages to get them in the correct order
        messages.reverse()
        
        # Create a JSON file to store the conversation
        conversation = []
        for message in messages:
            role = message['role']
            content = message['content'][0]['text']['value'] if message['content'] else "No content"
            conversation.append({"role": role, "content": content})

        # Pass the conversation data to the summarization model
        summary = summarise_conversation(conversation)
        
        # Add the summary to the top of the conversation
        conversation.insert(0, {"role": "summary_assistant", "content": summary})
        with open('conversation.json', 'w') as f:
            json.dump(conversation, f, indent=4)
        # Delete the thread
        # client.beta.threads.delete(thread_id=thread_id)
        return jsonify({"message": "Thread deleted successfully"})
    else:
        return jsonify({"error": "No thread_id provided"}), 400

if __name__ == '__main__':
    app.run(debug=True)
