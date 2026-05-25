import ollama

response = ollama.chat(
    model="phi3",
    messages=[
        {"role": "user", "content": "Explain operating system in simple words"}
    ]
)

print(response["message"]["content"])
