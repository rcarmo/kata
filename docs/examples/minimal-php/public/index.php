<?php
header('Content-Type: application/json');

echo json_encode([
    'status' => 'ok',
    'runtime' => 'php',
    'message' => 'Hello from Kata minimal PHP example!'
]);
