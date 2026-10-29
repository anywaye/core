
package generate

import (
	"os"
	"strings"
)

func Render(templatePath string, values map[string]string) (string, error) {
	raw, err := os.ReadFile(templatePath)
	if err != nil {
		return "", err
	}
	out := string(raw)
	for key, value := range values {
		out = strings.ReplaceAll(out, "{{"+key+"}}", value)
	}
	return out, nil
}
