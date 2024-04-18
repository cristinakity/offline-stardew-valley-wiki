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
    # if ($metaDescriptionMatch) {
    #     $metaDescription = $metaDescriptionMatch.Groups[1].Value
    # } else {
    #     $metaDescription = ""
    # }

    if ($metaKeywordsMatch) {
        $headContent = Get-Content -Path $file.FullName | Out-String
        $pageTitle = [regex]::Match($headContent, '<title>(.*?)<\/title>').Groups[1].Value
     
        $metaKeywords = $metaKeywordsMatch.Groups[1].Value
        # Add description to the meta keywords
        # validate if the description is not empty
        if ($metaDescriptionMatch) {
            $metaKeywords += ", " + $metaDescriptionMatch.Groups[1].Value
        }

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
    Write-Progress -Activity "Generating Search json" -Status "Processed file: $($fileName)" -PercentComplete $percentage
    # Write-Progress "Processed file: $($fileName)" -PercentComplete $percentage
    # Calculate the percentage of total HTML files processed and round it to 2 decimal places
    # Write-Progress "Percentage of total HTML files processed: $($percentage)%"
}
# Remove the last comma from the JSON file
(Get-Content -Path $resultJsonFilePath) -replace ',\s*$' | Set-Content -Path $resultJsonFilePath
# Add the closing square bracket to the JSON file
']' | Out-File -FilePath $resultJsonFilePath -Append

# # Convert the results array to JSON format
# $resultsJson = $results | ConvertTo-Json

# # Save the JSON data to a file
# $searchJsonFilePath = "$srcFolderPath/search.json"
# $resultsJson | Out-File -FilePath $searchJsonFilePath