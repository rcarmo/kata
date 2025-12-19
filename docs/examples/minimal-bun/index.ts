const port = Number(process.env.PORT || 8000);

const server = Bun.serve({
  port,
  fetch() {
    return new Response(
      JSON.stringify({ status: 'ok', runtime: 'bun', message: 'Hello from Kata minimal Bun example!' }),
      { headers: { 'content-type': 'application/json' } }
    );
  },
});

console.log(`Listening on http://0.0.0.0:${server.port}`);
