# Write-Warning "Error processing file: $($file.FullName). Error: $_"
# Ensure the logs folder exists
$logFolderPath = "logs"
if (-Not (Test-Path $logFolderPath)) {
    New-Item -ItemType Directory -Path $logFolderPath | Out-Null
}

# Create a log file with a timestamp
$timestamp = (Get-Date).ToString("yyyyMMddHHmmss")
$logFilePath = Join-Path -Path $logFolderPath -ChildPath "log_removeTmp_$timestamp.txt"

# Create the logfile
"[$(Get-Date)] Log file created." | Out-File -FilePath $logFilePath -Append

# Define the source folder path
$srcFolderPath = "src"
# Get all .tmp files in the source folder
$tmpFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.tmp" -Recurse

if ($tmpFiles.Count -eq 0) {
    Write-Host "No .tmp files found in the source folder."
} else {
    $count = 1
    # Delete each .tmp file
    foreach ($file in $tmpFiles) {
        Remove-Item -Path $file.FullName -Force

        $progress = [math]::Round(($count / $tmpFiles.Count) * 100)
        Write-Progress -Activity "Deleting .tmp files" -Status "Progress: $($file.Name) $progress%" -PercentComplete $progress

        $count++
    }
}

# Extract all .z files with extract here, do not replace existing files
$zFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.z" -Recurse
$count = 1

# Check if 7-Zip is installed
$sevenZipPath = "C:\Program Files\7-Zip\7z.exe"
if (-Not (Test-Path $sevenZipPath)) {
    Write-Error "7-Zip is not installed or not found at the expected path: $sevenZipPath"
    # add to the log file
    "[$(Get-Date)] 7-Zip not found at $sevenZipPath" | Out-File -FilePath $logFilePath -Append
    exit 1
}

if (-not $zFiles -or $zFiles.Count -eq 0) {
    Write-Host "No .z files found in the source folder."
    "[$(Get-Date)] No .z files found in the source folder." | Out-File -FilePath $logFilePath -Append
} else {
    foreach ($file in $zFiles) {
        try {
            # Use 7-Zip to extract .z files without showing output
            & $sevenZipPath x $file.FullName -o"$($file.DirectoryName)" -y *> $null
            if ($LASTEXITCODE -eq 0) {
                Remove-Item -Path $file.FullName -Force
                # Log to the log file
                "[$(Get-Date)] Extracted and deleted file: $($file.FullName)" | Out-File -FilePath $logFilePath -Append
            } else {
                # Log the error message, logfile
                "[$(Get-Date)] Failed to extract file: $($file.FullName)" | Out-File -FilePath $logFilePath -Append
            }
        } catch {
            # Log the error message
            "[$(Get-Date)] Error processing file: $($file.FullName). Error: $_" | Out-File -FilePath $logFilePath -Append
        }

        $progress = [math]::Round(($count / $zFiles.Count) * 100)
        Write-Progress -Activity "Extracting .z files" -Status "Progress: $($file.Name) $progress%" -PercentComplete $progress

        $count++
    }
}
