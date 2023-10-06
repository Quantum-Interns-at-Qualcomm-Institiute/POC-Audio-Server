import "../../css/RectangleWidget.css";

/* 
 * props.top-text: str
 * props.children: str
 * props.status: str
 *      - waiting: establishing connection
 *      - good: communicatons secure
 *      - bad:  eavesdropper detected
 */
export default function RectangleWidget(props) {

    return(
        <div className="rectangle-widget">
            <div>{props.topText}</div>
            <div class={`rectangle ${props.status}`}>{props.children}</div>
        </div>
    );
}