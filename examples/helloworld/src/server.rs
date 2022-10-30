mod api;
use async_trait::async_trait;

use actix_web::web;
use api::*;

#[async_trait(?Send)]
pub trait ServerState {}

struct DefaultServer;

#[async_trait(?Send)]
impl<S> ApiService<S> for DefaultServer
where
    S: ServerState + Send + Sync + 'static,
{
    async fn hello_user(
        _data: web::Data<S>,
        path: web::Path<HelloUserPath>,
    ) -> Result<String, Detailed<HelloUserError>> {
        Ok(format!("Hello, {}", path.user))
    }
}

pub async fn run_server<S>(bind: &str, initial_state: S) -> Result<(), std::io::Error>
where
    S: ServerState + Send + Sync + 'static,
{
    api::run_service::<DefaultServer, S>(bind, initial_state).await
}
