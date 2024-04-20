# Define the source folder path
$srcFolderPath = "src"
# Create the URL path by removing the unwanted part of the file path
$partToRemove = (Resolve-Path -Path $srcFolderPath).Path

# Get all HTML files inside the source folder
# $htmlFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.html" -Recurse
# Get all HTML files inside the source folder except those containing "mediawiki"
$htmlFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.html" -Recurse | Where-Object { $_.Name -notlike "*mediawiki*" }

# Initialize an empty array to store the URL paths and keywords
$results = @()

# Create an empty JSON file
$resultJsonFilePath = "$srcFolderPath/search.json"
'[' | Out-File -FilePath $resultJsonFilePath

# Loop through each HTML file
foreach ($file in $htmlFiles) {
    # Get the file name without extension
    $fileName = $file.Name -replace '\.html$'

    # Get the HTML meta data keywords (assuming they are stored in a <meta name="keywords" content="..." /> tag)
    $metaKeywordsMatch = (Get-Content -Path $file.FullName | Select-String -Pattern '<meta name="keywords" content="([^"]+)"' -AllMatches).Matches
    # Get the HTML meta data description (assuming it is stored in a <meta name="description" content="..." /> tag)
    $metaDescriptionMatch = (Get-Content -Path $file.FullName | Select-String -Pattern '<meta name="description" content="([^"]+)"' -AllMatches).Matches

    $metaKeywords = if ($metaKeywordsMatch) { $metaKeywordsMatch.Groups[1].Value } else { "" }
    # create a new string with the description, remove the commas and common words
    $description = if ($metaDescriptionMatch) { $metaDescriptionMatch.Groups[1].Value } else { "" }
    # Add description to the meta keywords
    # validate if the description is not empty
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
            Description = $metaDescriptionMatch.Groups[1].Value
        }

        # Add the result to the array
        $results += $result

        # Convert the result to JSON format
        $resultJson = $result | ConvertTo-Json

        # Save the JSON data to a file
        $resultJson | Out-File -FilePath $resultJsonFilePath -Append
        ',' | Out-File -FilePath $resultJsonFilePath -Append
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