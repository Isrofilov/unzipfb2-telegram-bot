<?php
$botToken = $_ENV['UNZIPFB2_BOTTOKEN'];
$apiURL = "https://api.telegram.org/bot$botToken/";
$allowedFileSize = 32 * 1024 * 1024; // 32 MB in bytes

function sendRequest($method, $parameters) {
	global $apiURL;
	$ch = curl_init($apiURL . $method);
	curl_setopt($ch, CURLOPT_POST, true);
	curl_setopt($ch, CURLOPT_POSTFIELDS, $parameters);
	curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
	$response = curl_exec($ch);
	curl_close($ch);
	return json_decode($response, true);
}

$update = json_decode(file_get_contents('php://input'), true);
$message = $update['message'];

// Check if the message contains a document
if (isset($message['document'])) {
	$fileId = $message['document']['file_id'];
	$fileSize = $message['document']['file_size'];
	
	if ($fileSize <= $allowedFileSize) {
		// Get the file path from Telegram
		$fileData = sendRequest('getFile', ['file_id' => $fileId]);
		$filePath = $fileData['result']['file_path'];
		$downloadURL = "https://api.telegram.org/file/bot$botToken/$filePath";

		// Download the file
		$zipFileContent = file_get_contents($downloadURL);
		$zipFileName = tempnam(sys_get_temp_dir(), 'zip');
		file_put_contents($zipFileName, $zipFileContent);

		// Open zip archive
		$zip = new ZipArchive;
		if ($zip->open($zipFileName) === true) {
			// Extract and find .fb2 file
			$extractPath = sys_get_temp_dir() . '/' . uniqid('fb2_', true);
			mkdir($extractPath);
			$zip->extractTo($extractPath);
			$zip->close();

			$files = new RecursiveIteratorIterator(
				new RecursiveDirectoryIterator($extractPath),
				RecursiveIteratorIterator::LEAVES_ONLY
			);

			foreach ($files as $name => $file) {
				if (!$file->isDir() && pathinfo($file->getFilename(), PATHINFO_EXTENSION) === 'fb2') {
					if (filesize($file->getRealPath()) <= $allowedFileSize) {
						// Send the .fb2 file back to user
						sendRequest('sendDocument', [
							'chat_id' => $message['chat']['id'],
							'document' => curl_file_create($file->getRealPath()),
							'caption' => 'Here is your .fb2 file'
						]);
					} else {
						// File is too large after extraction
						sendRequest('sendMessage', [
							'chat_id' => $message['chat']['id'],
							'text' => 'The .fb2 file exceeds the maximum allowed size of 32 MB after extraction.'
						]);
					}
					break;
				}
			}
			
			// Cleanup
			array_map('unlink', glob("$extractPath/*.*"));
			rmdir($extractPath);
		} else {
			// Failed to open zip archive
			sendRequest('sendMessage', [
				'chat_id' => $message['chat']['id'],
				'text' => 'Failed to open the ZIP archive.'
			]);
		}

		// Cleanup
		unlink($zipFileName);
	} else {
		// File is too large
		sendRequest('sendMessage', [
			'chat_id' => $message['chat']['id'],
			'text' => 'The file exceeds the maximum allowed size of 32 MB.'
		]);
	}
} else {
	sendRequest('sendMessage', ['chat_id' => $message['chat']['id'],'text' => 'Welcome to the Unzip Bot! 🤖

I\'m here to help you extract .fb2 files from zip archives. Just send me a zip file, and I\'ll handle the rest. If there are multiple .fb2 files, I\'ll extract the first one I find.']);

}

?>