# Define the source folder path
$srcFolderPath = "src"
# Create the URL path by removing the unwanted part of the file path
$partToRemove = (Resolve-Path -Path $srcFolderPath).Path

# create and array with the language codes
$languageCodes = "en", "es", "fr", "de", "it", "ja", "ko", "pt", "ru", "tr", "zh","hu";
$languageCodes = "es"; # for testing purposes

# For each language code, search inside src/lang_code.stardewvalleywiki.com/ for html files
# Initialize an empty array to store the URL paths and keywords
$results = @()

# Create logs folder if it doesn't exist
$logsFolderPath = "logs"
if (-not (Test-Path -Path $logsFolderPath)) {
    New-Item -ItemType Directory -Path $logsFolderPath | Out-Null
}

# Generate log file name with timestamp
$timestamp = (Get-Date).ToString("yyyyMMddHHmmss")

# Create an empty JSON file for each language
foreach ($lang in $languageCodes) {

    $resultJsonFilePath = "$srcFolderPath/search.json"
    $languageFolderPath = "$srcFolderPath/stardewvalleywiki.com"
    if($lang -ne "en") {
        $resultJsonFilePath = "$srcFolderPath/$lang.search.json"
        $languageFolderPath = "$srcFolderPath/$lang.stardewvalleywiki.com"
    }

    $logFilePath = "$logsFolderPath/log_langSearch_($lang)_$timestamp.txt"
    # Initialize log file
    "Log for language search JSON generation - $timestamp" | Out-File -FilePath $logFilePath

    # Log the start of processing for the current language
    Write-Host "Processing language: $lang"
    "Processing language: $lang" | Out-File -FilePath $logFilePath -Append

    # Create the file 
    '[' | Out-File -FilePath $resultJsonFilePath

    # Show info about the current language folders and file
    # Write-

    # Get all HTML files inside the source folder
    # $htmlFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.html" -Recurse
    # Get all HTML files inside the source folder except those containing "mediawiki"
    $htmlFiles = Get-ChildItem -Path $languageFolderPath -Filter "*.html" -Recurse | Where-Object { $_.FullName -notmatch "\\mediawiki\\" -and $_.Name -notlike "*mediawiki*" }

    # Loop through each HTML file
    foreach ($file in $htmlFiles) {
        # Get the file name without extension
        $fileName = $file.Name -replace '\.html$'

        # Get html title
        $htmlTitle = [regex]::Match((Get-Content -Path $file.FullName | Out-String), '<title>(.*?)<\/title>').Groups[1].Value

        # Get the HTML meta data keywords (assuming they are stored in a <meta name="keywords" content="([^"]+)" /> tag)
        $metaKeywordsMatch = (Get-Content -Path $file.FullName | Select-String -Pattern '<meta name="keywords" content="([^"]+)"' -AllMatches).Matches
        # Get the HTML meta data description (assuming it is stored in a <meta name="description" content="([^"]+)"' -AllMatches).Matches
        $metaDescriptionMatch = (Get-Content -Path $file.FullName | Select-String -Pattern '<meta name="description" content="([^"]+)"' -AllMatches).Matches

        $metaKeywords = if ($metaKeywordsMatch) { $metaKeywordsMatch.Groups[1].Value } else { "" }
        $description = if ($metaDescriptionMatch -and $metaDescriptionMatch.Count -gt 0) { 
            $metaDescriptionMatch[0].Groups[1].Value 
        } else { 
            $htmlTitle # fallback to the title if no description is found
        }
        # create a new string with the description, remove the commas and common words
        if ($description) {
            $description = $description -replace ',', ''
            # $commonWords = "common_word1", "common_word2", "common_word3", "the", "and", "in", "on"
            # $description = $description -replace ($commonWords -join "|"), ''

            # Add the description to the meta keywords
            # validate if metaKeywords is not empty
            if ($metaKeywords) {
                $metaKeywords += ", " + $description
            } else {
                $metaKeywords = $description
            }
        }

        if ($metaKeywords) {
            $headContent = Get-Content -Path $file.FullName | Out-String
            $pageTitle = [regex]::Match($headContent, '<title>(.*?)<\/title>').Groups[1].Value
        
            $urlPath = $file.FullName -replace [regex]::Escape($partToRemove), ""

            # Create an object with the URL path and keywords
            $result = [PSCustomObject]@{
                UrlPath = "." + $urlPath
                Title = $pageTitle
                Keywords = $metaKeywords -split ','
                Description = $description
            }

            # Add the result to the array
            $results += $result

            # Convert the result to JSON format
            $resultJson = $result | ConvertTo-Json

            # Save the JSON data to a file
            $resultJson | Out-File -FilePath $resultJsonFilePath -Append
            ',' | Out-File -FilePath $resultJsonFilePath -Append

            # Log the processed file
            "Processed file: $($file.FullName)" | Out-File -FilePath $logFilePath -Append
        }

        # Show progress
        $percentage = [Math]::Round(($results.Count / $htmlFiles.Count) * 100, 2)
        $percentage = if ($percentage -gt 100) { 100 } else { $percentage }
        Write-Progress -Activity "Generating Search json" -Status "Processed file $($percentage)% $($fileName)" -PercentComplete $percentage
        # Write-Progress "Processed file: $($fileName)" -PercentComplete $percentage
        # Calculate the percentage of total HTML files processed and round it to 2 decimal places
        # Write-Progress "Percentage of total HTML files processed: $($percentage)%"
        if($percentage -eq 100) {
            Write-Progress -Activity "Generating Search json" -Status "Completed" -Completed
            break;
        }
    }
    # Read the whole file as string
    $fileContent = Get-Content -Path $resultJsonFilePath
    # Remove the last comma from the JSON file
    $lineCount = $fileContent.Count
    $index = 0;
    $fileContent = foreach ($line in $fileContent) {
        $index++
        if ($lineCount -eq $index) {
            $line -replace ',\s*$', ''
        } else {
            $line
        }
    }
    # Save the updated content back to the file
    $fileContent | Set-Content -Path $resultJsonFilePath
    # Add the closing square bracket to the JSON file
    ']' | Out-File -FilePath $resultJsonFilePath -Append

    # Log completion of the current language
    "Completed processing for language: $lang" | Out-File -FilePath $logFilePath -Append
    Write-Host "Completed processing for language: $lang"
    # Show final progress
    Write-Progress -Activity "Generating Search json" -Status "Completed for $lang" -Completed
    # Add a blank line to the log for readability
    "" | Out-File -FilePath $logFilePath -Append
    # Check if the file was created successfully
    if (Test-Path -Path $resultJsonFilePath) {
        Write-Host "Search JSON file created successfully: $resultJsonFilePath"
    } else {
        Write-Host "Failed to create the search JSON file: $resultJsonFilePath"
        "Failed to create the search JSON file: $resultJsonFilePath" | Out-File -FilePath $logFilePath -Append
    }
    # Check if the file is not empty
    if ((Get-Content -Path $resultJsonFilePath).Length -eq 0) {
        Write-Host "The search JSON file is empty: $resultJsonFilePath"
        "The search JSON file is empty: $resultJsonFilePath" | Out-File -FilePath $logFilePath -Append
    } else {
        Write-Host "The search JSON file is not empty: $resultJsonFilePath"
    }
}

# Log overall completion
"Search JSON generation completed successfully." | Out-File -FilePath $logFilePath -Append