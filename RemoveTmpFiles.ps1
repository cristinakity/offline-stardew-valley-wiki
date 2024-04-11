# Define the source folder path
$srcFolderPath = "src"

# Get all .tmp files in the source folder
$tmpFiles = Get-ChildItem -Path $srcFolderPath -Filter "*.tmp" -Recurse
$count = 1;
# Delete each .tmp file
foreach ($file in $tmpFiles) {
    Remove-Item -Path $file.FullName -Force

    $progress = [math]::Round(($count / $tmpFiles.Count) * 100)
    Write-Progress -Activity "Deleting .tmp files" -Status "Progress: $($file.FileName) $progress%" -PercentComplete $progress

    $count++
}