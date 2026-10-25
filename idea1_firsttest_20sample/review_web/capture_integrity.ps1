# Source-media validation shared by initial exports and later scene updates.
# This module reads record fields only; it never creates/reconstructs photographs.
function RV-CaptureFailureText([string]$ErrorText) {
    if($ErrorText -match 'Observation intervention changed native state|Observer intervention changed native task state'){return '服务器取景时检测到场景状态改变，该次图像未被采纳。'}
    if($ErrorText -match 'observer_disabled_after_previous_error'){return '此前取景已失败，服务器关闭了本次尝试的后续取景，因此没有生成这一阶段的证据图。'}
    if($ErrorText -match 'No relevant target pixels|No third-party view contains'){return '服务器没有找到含足够目标像素的视角，未生成可用证据图。'}
    if($ErrorText -match 'No local evidence camera region'){return '服务器未得到适合目标对象的相机候选区域，未生成证据图。'}
    if($ErrorText){return '服务器取景失败：'+$ErrorText}
    return '原始记录没有图片路径，也没有可用的视角图片；不能从网页重建该图。'
}
function RV-MediaInfo([string]$Root,[string]$Relative,[string]$Boundary,$Capture=$null) {
    $error=[string](RV-Get $Capture 'capture_error' '')
    if(-not $error){$error=[string](RV-Get (RV-Get $Capture 'camera_audit' @{}) 'error' '')}
    $info=[ordered]@{source_path=$Relative;source_status='available';source_error=$error;source_message='';resolved_path=$null;observation_contaminated=[bool](RV-Get (RV-Get $Capture 'camera_audit' @{}) 'world_state_changed' $false)}
    if([string]::IsNullOrWhiteSpace($Relative)){$info.source_status=if($error){'generation_failed'}else{'path_not_recorded'};$info.source_message=RV-CaptureFailureText $error;return $info}
    if([IO.Path]::IsPathRooted($Relative)){$info.source_status='invalid_path';$info.source_message='图片路径是绝对路径，不能按跨机器导出契约直接使用；需由导出端保存相对路径。';return $info}
    $path=[IO.Path]::GetFullPath((Join-Path $Root $Relative));$prefix=[IO.Path]::GetFullPath($Boundary).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
    if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){$info.source_status='invalid_path';$info.source_message='图片路径越出当前数据目录，未读取。';return $info}
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){$info.source_status='file_missing';$info.source_message='原始记录有图片路径，但本地文件不存在；需核对服务器打包或本地拷贝。';return $info}
    $info.resolved_path=$path
    if($error -or $info.observation_contaminated){$info.source_status='capture_invalid';$info.source_message=RV-CaptureFailureText $error}
    return $info
}
function RV-SummarizeMedia($Frames) {
    $counts=[ordered]@{display_items=0;declared_image_paths=0;available_image_refs=0;generation_failed_items=0;path_not_recorded_items=0;missing_files=0;invalid_paths=0;invalid_captures=0;issue_items=0}
    foreach($frame in @($Frames)){
        $counts.display_items++
        if([string](RV-Get $frame 'source_path' '')){$counts.declared_image_paths++}
        if(RV-Get $frame 'src'){$counts.available_image_refs++}
        $status=[string](RV-Get $frame 'source_status' $(if(RV-Get $frame 'src'){'available'}else{'path_not_recorded'}))
        switch($status){'generation_failed'{$counts.generation_failed_items++};'path_not_recorded'{$counts.path_not_recorded_items++};'file_missing'{$counts.missing_files++};'invalid_path'{$counts.invalid_paths++};'capture_invalid'{$counts.invalid_captures++}}
        if($status -ne 'available'){$counts.issue_items++}
    }
    $counts['status']=if($counts.issue_items){'source_incomplete'}else{'media_present_not_visually_approved'}
    return $counts
}
