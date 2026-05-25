document.addEventListener("DOMContentLoaded", () => {
  const chatBox = document.getElementById("chat-box");
  const userInput = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");

  // Send message on button click or Enter key
  sendBtn.addEventListener("click", sendMessage);
  userInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      sendMessage();
    }
  });

  function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    // User message bubble (right side, new line)
    const userMsg = document.createElement("div");
    userMsg.classList.add("message", "user");
    userMsg.textContent = text;
    chatBox.appendChild(userMsg);

    userInput.value = "";
    chatBox.scrollTop = chatBox.scrollHeight;

    // Show typing indicator while waiting (left side)
    const typingIndicator = document.createElement("div");
    typingIndicator.classList.add("typing");
    typingIndicator.textContent = "🤖 AI is thinking...";
    chatBox.appendChild(typingIndicator);
    chatBox.scrollTop = chatBox.scrollHeight;

    // Call backend
    fetch("/mentor/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text })
    })
      .then(res => res.json())
      .then(data => {
        // Remove typing indicator
        if (chatBox.contains(typingIndicator)) {
          chatBox.removeChild(typingIndicator);
        }
        // Show bot reply with typing effect
        typeBotMessage(data.answer);
      })
      .catch(err => {
        console.error("Error:", err);
        if (chatBox.contains(typingIndicator)) {
          chatBox.removeChild(typingIndicator);
        }
        displayBotMessage("⚠️ Error: Could not connect to mentor backend.");
      });
  }

  // Typing effect for bot replies (left side, new line)
  function typeBotMessage(text) {
    const botMsg = document.createElement("div");
    botMsg.classList.add("message", "bot");
    chatBox.appendChild(botMsg);

    let i = 0;
    const interval = setInterval(() => {
      botMsg.textContent += text.charAt(i);
      i++;
      chatBox.scrollTop = chatBox.scrollHeight;
      if (i >= text.length) clearInterval(interval);
    }, 30); // typing speed
  }

  // Fallback instant bot message
  function displayBotMessage(text) {
    const botMsg = document.createElement("div");
    botMsg.classList.add("message", "bot");
    botMsg.textContent = text;
    chatBox.appendChild(botMsg);
    chatBox.scrollTop = chatBox.scrollHeight;
  }
});
