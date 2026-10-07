package test

import "testing"

func TestBehaviour(t *testing.T) {
	response := GetUser(1)
	if response.Name != "Alice" {
		t.Errorf("got %s, want Alice", response.Name)
	}
}
