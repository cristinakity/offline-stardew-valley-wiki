$srcFolderPath = "src"

# Get all HTML files in the directory
$htmlFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.html" -File -Recurse

# Initialize progress variables
$totalFiles = $htmlFiles.Count
$completedFiles = 0
$startTime = Get-Date

# Loop through each HTML file
foreach ($file in $htmlFiles) {
    # Update progress
    $completedFiles++
    $progressPercentage = ($completedFiles / $totalFiles) * 100
    $progressPercentage = [Math]::Round($progressPercentage, 2)

    Write-Progress -Activity "Removing White lines" -Status "Processing file $completedFiles of $totalFiles ($progressPercentage%)" -PercentComplete $progressPercentage

    # Read the content of the file
    $content = Get-Content -Path $file.FullName -Raw

    # Remove white spaces only after </html>
    $content = $content -replace "(?m)</html>\s*$", "</html>"

    # Write the modified content back to the file
    $content | Set-Content -Path $file.FullName
}

# Calculate time elapsed
$endTime = Get-Date
$totalTime = $endTime - $startTime

# Clear progress when done
Write-Progress -Activity "Removing White lines" -Completed

# Display start and end date, and total time
"Started: $startTime"
"Ended: $endTime"
"Total Time: $totalTime"