while true; do
    sudo env/bin/cynthia ${@:1}
    case $? in
        0)
            break
            ;;
        1)
            break
            ;;
        *)
            ;;
    esac
done
