param(
    [string]$InputDocx = '',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $InputDocx) { $InputDocx = Join-Path $projectRoot 'output/deliverables/MathorCup项目全过程与当前进度.docx' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'output/document_qa/project_roadmap' }
$InputDocx = (Resolve-Path -LiteralPath $InputDocx).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$pdfPath = Join-Path $OutputDirectory 'project-roadmap.pdf'
$roadmapWord = $null
$roadmapDocument = $null
try {
    # Native Microsoft Word export on Windows; installation is discovered by COM.
    # Open only the generated document read-only; leave existing WPS/user documents untouched.
    $roadmapWord = New-Object -ComObject Word.Application
    $roadmapWord.Visible = $false
    $roadmapWord.DisplayAlerts = 0
    $roadmapDocument = $roadmapWord.Documents.Open($InputDocx, $false, $true)
    $roadmapDocument.Repaginate()
    $pageCount = $roadmapDocument.ComputeStatistics(2)
    $roadmapDocument.ExportAsFixedFormat($pdfPath, 17)
    [pscustomobject]@{ Source = $InputDocx; Pdf = $pdfPath; Pages = $pageCount } | ConvertTo-Json
}
finally {
    if ($null -ne $roadmapDocument) {
        $roadmapDocument.Close(0)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($roadmapDocument)
    }
    if ($null -ne $roadmapWord) {
        if ($roadmapWord.Documents.Count -eq 0) { $roadmapWord.Quit(0) }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($roadmapWord)
    }
}
