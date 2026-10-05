{{/* Labels shared by every object of one service. Call with (dict "root" $ "name" $name). */}}
{{- define "corportal.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/part-of: corportal
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
{{- end -}}

{{- define "corportal.selector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "corportal.image" -}}
{{- $g := .root.Values.global -}}
{{- $svc := index .root.Values.services .name | default dict -}}
{{- printf "%s/%s/%s:%s" $g.registry $g.imagePrefix .name (toString ($svc.imageTag | default $g.imageTag)) -}}
{{- end -}}

{{/* Vault Agent template: every key of the KV v2 secret as an `export KEY='value'` line. */}}
{{- define "corportal.vaultTemplate" -}}
{{- $path := printf "%s/%s" .root.Values.vault.secretPathPrefix .name -}}
{{ printf "{{- with secret %q -}}" $path }}
{{ "{{- range $k, $v := .Data.data }}" }}
{{ "export {{ $k }}='{{ $v }}'" }}
{{ "{{ end }}" }}
{{ "{{- end -}}" }}
{{- end -}}
