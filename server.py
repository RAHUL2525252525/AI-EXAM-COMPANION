import ollama

while True:
    q = input("You: ")
    if q.lower() == "exit":
        break

    res = ollama.chat(
        model="phi3",
        messages=[{"role": "user", "content": q}]
    )

    print("AI:", res["message"]["content"])
