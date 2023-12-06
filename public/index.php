<?php
require_once __DIR__ . '/../vendor/autoload.php';

$dotenv = Dotenv\Dotenv::createImmutable(__DIR__ . '/..');
$dotenv->load();

$bot = mb_substr($_SERVER['REQUEST_URI'], 1);

$telegram_hook_path = $_ENV['unzipfb2_HOOK_PATH'];

switch ($bot) {
	case $telegram_hook_path:
		require_once '../app/unzipfb2.php';
		break;
	default:
		exit('Unknown bot.');
}