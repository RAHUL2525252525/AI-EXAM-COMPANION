const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json());
app.use(express.static("public"));

/* ---------- LOAD QUESTIONS STAGE-WISE ---------- */
app.post("/mocktest/generate", (req, res) => {
  const { stage } = req.body;

  // stage = "1" | "2" | "3" ...
  const filePath = path.join(__dirname, "question_bank", `stage${stage}.json`);

  if (!fs.existsSync(filePath)) {
    return res.json({ questions: [] });
  }

  const data = JSON.parse(fs.readFileSync(filePath, "utf8"));

  res.json({ questions: data.questions });
});

/* ---------- SAVE RESULT ---------- */
app.post("/mocktest/result", (req, res) => {
  const { correct, wrong, score, total } = req.body;

  const results = JSON.parse(fs.readFileSync("results.json", "utf8"));

  results.anonymous.push({
    correct,
    wrong,
    score,
    total,
    date: new Date().toISOString()
  });

  fs.writeFileSync("results.json", JSON.stringify(results, null, 2));

  res.send(`
    <h1>✅ Test Completed</h1>
    <p>Total Questions: ${total}</p>
    <p>Correct: ${correct}</p>
    <p>Wrong: ${wrong}</p>
    <p>Score: ${score}</p>
    <a href="/mocktest.html">Retry</a>
  `);
});

/* ---------- START SERVER ---------- */
app.listen(3000, () => {
  console.log("✅ Server running at http://localhost:3000");
}); 