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

    Write-Progress -Activity "Removing Unnecessary changes" -Status "Processing file $completedFiles of $totalFiles ($progressPercentage%)" -PercentComplete $progressPercentage

    # Read the content of the file
    $content = Get-Content -Path $file.FullName -Raw

    # Remove meta property="article:modified_time"
    $content = $content -replace ".*<meta property=`"article:modified_time`".*?>.*\r?\n?", ""

    # Remove meta property="article:published_time"
    $content = $content -replace "<meta property=`"article:published_time`".*?>.*\r?\n?", ""    
    
    # # Remove <script type="application/ld+json"
    # $content = $content -replace "<script type=`"application/ld\+json`".*?</script>", ""

    # Set wgRequestId to a fixed value
    $content = $content -replace '(wgRequestId":")[^"]*', '${1}0a905c927b9ecf60e299227a'

    # Set wgBackendResponseTime to a fixed value of 127
    $content = $content -replace '(wgBackendResponseTime":)\d+', '${1}127'

    # Normalize cputime and walltime to fixed values
    $content = $content -replace '(cputime":")[^"]*', '${1}0.000'
    $content = $content -replace '(walltime":")[^"]*', '${1}0.000'

    # Normalize timestamp to a fixed value
    $content = $content -replace '(timestamp":")[^"]*', '${1}0000000000'

    # Normalize wgRevisionId and wgCurRevisionId to fixed values
    $content = $content -replace '(wgRevisionId":)\d+', '${1}26668'
    $content = $content -replace '(wgCurRevisionId":)\d+', '${1}26668'

    # Normalize dateModified and datePublished in JSON-LD to fixed values
    $content = $content -replace '("dateModified":")[^"]*', '${1}2024-11-02T06:01:03Z'
    $content = $content -replace '("datePublished":")[^"]*', '${1}2024-11-02T06:01:03Z'

    # Normalize wgPageParseReport metrics to fixed values
    $content = $content -replace '(ppvisitednodes":{"value":)\d+', '${1}1996'
    $content = $content -replace '(postexpandincludesize":{"value":)\d+', '${1}11548'
    $content = $content -replace '(templateargumentsize":{"value":)\d+', '${1}166'
    $content = $content -replace '(expansiondepth":{"value":)\d+', '${1}8'
    $content = $content -replace '(timingprofile":\[.*?\])', 'timingprofile":[]'

    # Write the modified content back to the file
    $content | Set-Content -Path $file.FullName
}

# Calculate time elapsed
$endTime = Get-Date
$totalTime = $endTime - $startTime

# Clear progress when done
Write-Progress -Activity "Removing HTTrack comments" -Completed

# Display start and end date, and total time
"Started: $startTime"
"Ended: $endTime"
"Total Time: $totalTime"