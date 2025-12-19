const express = require('express');

const app = express();
const port = process.env.PORT || 8000;

app.get('/', (_req, res) => {
  res.json({ status: 'ok', runtime: 'nodejs', message: 'Hello from Kata minimal Node.js example!' });
});

app.listen(port, '0.0.0.0', () => {
  // Basic startup log so you can confirm the port inside the container
  console.log(`Listening on http://0.0.0.0:${port}`);
});
