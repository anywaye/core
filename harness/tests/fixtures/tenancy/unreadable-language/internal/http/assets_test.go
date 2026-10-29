package http

import "testing"

func TestGetAssetIsAbsentWithoutAnAccount(t *testing.T) {
	srv := newServer(t, noAccount, "a1")
	resp := srv.Get("/v1/assets/a1")
	assertBody(t, resp, not_found)
}

func TestGetAssetIsAbsentForAnotherAccount(t *testing.T) {
	srv := newServer(t, otherAccount, "b1")
	resp := srv.Get("/v1/assets/a1")
	assertBody(t, resp, not_found)
}

func TestGetAssetSeesItsOwnRow(t *testing.T) {
	srv := newServer(t, myAccount, "a1")
	resp := srv.Get("/v1/assets/a1")
	assertBody(t, resp, object_key)
}