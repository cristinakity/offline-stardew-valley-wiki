# Define the source folder path
$srcFolderPath = "src"
# Create the URL path by removing the unwanted part of the file path
$partToRemove = (Resolve-Path -Path $srcFolderPath).Path

# create and array with the language codes
$languageCodes = "en", "es", "fr", "de", "it", "ja", "ko", "pt", "ru", "tr", "zh","hu";
$languageCodes = "de"; # for testing purposes

# For each language code, search inside src/lang_code.stardewvalleywiki.com/ for html files
# Initialize an empty array to store the URL paths and keywords
$results = @()

# Generate log file name with timestamp
$timestamp = (Get-Date).ToString("yyyyMMddHHmmss")

# Create an empty JSON file for each language
foreach ($lang in $languageCodes) {

    $resultJsonFilePath = "$srcFolderPath/search.json"
    if($lang -ne "en") {
        $resultJsonFilePath = "$srcFolderPath/$lang.search.json"
    }

    # read the file content and order it by UrlPath
    if (Test-Path $resultJsonFilePath) {
        $fileContent = Get-Content -Path $resultJsonFilePath | ConvertFrom-Json
        $orderedContent = $fileContent | Sort-Object -Property UrlPath
        $orderedContent | ConvertTo-Json -Depth 10 | Set-Content -Path $resultJsonFilePath
    }

}
